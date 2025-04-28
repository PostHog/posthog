use crate::unordered_trends::AggregateFunnelRowUnordered;
use crate::PropVal;
use itertools::Itertools;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::str::FromStr;
use uuid::Uuid;

fn deserialize_number_from_string<'de, D>(deserializer: D) -> Result<u64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let s = String::deserialize(deserializer)?;
    u64::from_str(&s).map_err(serde::de::Error::custom)
}

#[derive(Clone, Deserialize)]
pub struct EnteredTimestamp {
    pub timestamp: f64,
    pub excluded: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Event {
    pub timestamp: f64,
    #[serde(deserialize_with = "deserialize_number_from_string")]
    pub interval_start: u64,
    pub uuid: Uuid,
    pub breakdown: PropVal,
    pub steps: Vec<i8>,
}

#[derive(Deserialize)]
pub struct Args {
    pub from_step: usize,
    pub to_step: usize,
    pub num_steps: usize,
    pub conversion_window_limit: u64, // In seconds
    pub breakdown_attribution_type: String,
    pub funnel_order_type: String,
    pub prop_vals: Vec<PropVal>,
    pub value: Vec<Event>,
}

// The Exclusion enum is used to label the max step
// A full exclusion is when there has been an event, a matching exclusion, and a matching event
// A partial exclusion is when there has been an event, and a matching exclusion
#[derive(PartialEq)]
pub enum Exclusion {
    Not,
    Partial,
    Full,
}

// Interval start, 1 or -1, the propval, and the event uuid
#[derive(Serialize)]
pub struct ResultStruct(pub u64, pub i8, pub PropVal, pub Uuid);

pub struct MaxStep {
    pub step: usize,
    pub timestamp: f64,
    pub excluded: Exclusion,
    pub event_uuid: Uuid,
}

struct IntervalData {
    max_step: MaxStep,
    entered_timestamp: Vec<EnteredTimestamp>,
}

pub type ResultsMap = HashMap<u64, ResultStruct>;

struct Vars {
    interval_start_to_entered_timestamps: HashMap<u64, IntervalData>,
    results: ResultsMap,
}

struct AggregateFunnelRow {
    breakdown_step: Option<usize>,
}

const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    excluded: false,
};

pub fn process_line(line: &str) -> Value {
    let args = parse_args(line);
    if args.funnel_order_type == "unordered" {
        let mut aggregate_funnel_row = AggregateFunnelRowUnordered {
            breakdown_step: Option::None,
        };
        let result = aggregate_funnel_row.calculate_funnel_from_user_events(&args);
        return json!({ "result": result });
    }
    let mut aggregate_funnel_row = AggregateFunnelRow {
        breakdown_step: Option::None,
    };
    let result: Vec<ResultStruct> = aggregate_funnel_row.calculate_funnel_from_user_events(&args);
    json!({ "result": result })
}

#[inline(always)]
fn parse_args(line: &str) -> Args {
    serde_json::from_str(line).expect("Invalid JSON input")
}

impl AggregateFunnelRow {
    #[inline(always)]
    fn calculate_funnel_from_user_events(&mut self, args: &Args) -> Vec<ResultStruct> {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        args.prop_vals
            .iter()
            .flat_map(|prop_val| {
                let results_map = self.loop_prop_val(args, prop_val);
                results_map.into_values().collect::<Vec<ResultStruct>>()
            })
            .collect()
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) -> ResultsMap {
        let mut vars = Vars {
            results: HashMap::new(),
            interval_start_to_entered_timestamps: HashMap::new(),
        };

        let filtered_events = args
            .value
            .iter()
            .filter(|e| {
                if args.breakdown_attribution_type == "all_events" {
                    e.breakdown == *prop_val
                } else {
                    true
                }
            })
            .group_by(|e| e.timestamp);

        for (_timestamp, events_with_same_timestamp) in &filtered_events {
            let events_with_same_timestamp: Vec<_> = events_with_same_timestamp.collect();
            for event in events_with_same_timestamp {
                self.process_event(args, &mut vars, event, prop_val);
            }
        }

        // At this point, everything left in entered_timestamps is an entry, but not an exit, if it has made it to from_step
        // When there is an exclusion, we drop all partial matches and only return full matches
        let fully_excluded = vars
            .interval_start_to_entered_timestamps
            .values()
            .find(|interval_data| interval_data.max_step.excluded == Exclusion::Full);
        if fully_excluded.is_none() {
            for (interval_start, interval_data) in
                vars.interval_start_to_entered_timestamps.into_iter()
            {
                if !vars.results.contains_key(&interval_start)
                    && interval_data.max_step.step >= args.from_step
                    && interval_data.max_step.excluded != Exclusion::Partial
                {
                    vars.results.insert(
                        interval_start,
                        ResultStruct(
                            interval_start,
                            -1,
                            prop_val.clone(),
                            interval_data.max_step.event_uuid,
                        ),
                    );
                }
            }
        }

        vars.results
    }

    #[inline(always)]
    fn process_event(&mut self, args: &Args, vars: &mut Vars, event: &Event, prop_val: &PropVal) {
        for step in event.steps.iter().rev() {
            let mut exclusion = false;
            let step = (if *step < 0 {
                exclusion = true;
                -*step
            } else {
                *step
            }) as usize;

            let is_unmatched_step_attribution = self
                .breakdown_step
                .map(|breakdown_step| step - 1 == breakdown_step)
                .unwrap_or(false)
                && *prop_val != event.breakdown;

            if step == 1 {
                if !is_unmatched_step_attribution
                    && !vars.results.contains_key(&event.interval_start)
                {
                    let entered_timestamp_one = EnteredTimestamp {
                        timestamp: event.timestamp,
                        excluded: false,
                    };
                    let interval = vars
                        .interval_start_to_entered_timestamps
                        .get_mut(&event.interval_start);
                    if interval.is_none()
                        || interval
                            .as_ref()
                            .map(|interval| {
                                interval.max_step.step == 1
                                    && interval.max_step.excluded != Exclusion::Not
                            })
                            .unwrap()
                    {
                        let mut entered_timestamp =
                            vec![DEFAULT_ENTERED_TIMESTAMP.clone(); args.num_steps + 1];
                        entered_timestamp[1] = entered_timestamp_one;
                        let interval_data = IntervalData {
                            max_step: MaxStep {
                                step: 1,
                                timestamp: event.timestamp,
                                excluded: Exclusion::Not,
                                event_uuid: event.uuid,
                            },
                            entered_timestamp: entered_timestamp,
                        };
                        vars.interval_start_to_entered_timestamps
                            .insert(event.interval_start, interval_data);
                    } else {
                        interval.unwrap().entered_timestamp[1] = entered_timestamp_one;
                    }
                }
            } else {
                vars.interval_start_to_entered_timestamps.retain(
                    |&interval_start, interval_data| {
                        let in_match_window = interval_data.entered_timestamp[step - 1].timestamp
                            != 0.0
                            && (event.timestamp
                                - interval_data.entered_timestamp[step - 1].timestamp)
                                <= args.conversion_window_limit as f64;
                        let previous_step_excluded =
                            interval_data.entered_timestamp[step - 1].excluded;
                        let already_reached_this_step = interval_data.entered_timestamp[step]
                            .timestamp
                            == interval_data.entered_timestamp[step - 1].timestamp;
                        if in_match_window && !already_reached_this_step {
                            if exclusion {
                                if !previous_step_excluded {
                                    interval_data.entered_timestamp[step - 1].excluded = true;
                                    if interval_data.max_step.step == step - 1 {
                                        let max_timestamp_in_match_window = (event.timestamp
                                            - interval_data.max_step.timestamp)
                                            <= args.conversion_window_limit as f64;
                                        if max_timestamp_in_match_window {
                                            interval_data.max_step.excluded = Exclusion::Partial;
                                        }
                                    }
                                }
                            } else {
                                if !is_unmatched_step_attribution {
                                    if !previous_step_excluded {
                                        interval_data.entered_timestamp[step] = EnteredTimestamp {
                                            timestamp: interval_data.entered_timestamp[step - 1]
                                                .timestamp,
                                            excluded: false,
                                        };
                                    }
                                    // check if we have hit the goal. if we have, remove it from the list and add it to the successful_timestamps
                                    if interval_data.entered_timestamp[args.to_step].timestamp
                                        != 0.0
                                    {
                                        vars.results.insert(
                                            interval_start,
                                            ResultStruct(
                                                interval_start,
                                                1,
                                                prop_val.clone(),
                                                event.uuid,
                                            ),
                                        );
                                        return false;
                                    } else if step > interval_data.max_step.step
                                        || (step == interval_data.max_step.step
                                            && interval_data.max_step.excluded
                                                == Exclusion::Partial)
                                    {
                                        interval_data.max_step = MaxStep {
                                            step: step,
                                            event_uuid: event.uuid,
                                            timestamp: event.timestamp,
                                            excluded: if previous_step_excluded {
                                                Exclusion::Full
                                            } else {
                                                Exclusion::Not
                                            },
                                        };
                                    }
                                }
                            }
                        }
                        true
                    },
                )
            }
        }
        // If a strict funnel, clear all of the steps that we didn't match to
        if args.funnel_order_type == "strict" {
            for interval_data in vars.interval_start_to_entered_timestamps.values_mut() {
                for i in 1..interval_data.entered_timestamp.len() {
                    if !event.steps.contains(&(i as i8)) {
                        interval_data.entered_timestamp[i] = DEFAULT_ENTERED_TIMESTAMP;
                    }
                }
            }
        }
    }
}
