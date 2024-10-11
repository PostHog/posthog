use std::collections::HashMap;
use std::str::FromStr;
use itertools::Itertools;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use crate::PropVal;

fn deserialize_number_from_string<'de, D>(deserializer: D) -> Result<u64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let s = String::deserialize(deserializer)?;
    u64::from_str(&s).map_err(serde::de::Error::custom)
}

#[derive(Clone, Deserialize)]
struct EnteredTimestamp {
    timestamp: f64,
    timings: Vec<f64>,
}

#[derive(Clone, Deserialize)]
struct Event {
    timestamp: f64,
    #[serde(deserialize_with = "deserialize_number_from_string")]
    interval_start: u64,
    breakdown: PropVal,
    steps: Vec<i8>,
}

#[derive(Deserialize)]
struct Args {
    from_step: usize,
    num_steps: usize,
    conversion_window_limit: u64, // In seconds
    breakdown_attribution_type: String,
    funnel_order_type: String,
    prop_vals: Vec<PropVal>,
    value: Vec<Event>,
}

#[derive(Serialize)]
struct ResultStruct(u64, i8, PropVal);

struct Vars {
    interval_start_to_entered_timestamps: HashMap<u64, Vec<EnteredTimestamp>>,
}

struct AggregateFunnelRow {
    breakdown_step: Option<usize>,
    results: HashMap<u64, ResultStruct>,
}

const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    timings: vec![],
};

pub fn process_line(line: &str) -> Value {
    let args = parse_args(&line);
    let mut aggregate_funnel_row = AggregateFunnelRow {
        results: HashMap::new(),
        breakdown_step: Option::None,
    };
    aggregate_funnel_row.calculate_funnel_from_user_events(&args);
    let result: Vec<ResultStruct> = aggregate_funnel_row.results.into_values().collect();
    json!({ "result": result })
}

#[inline(always)]
fn parse_args(line: &str) -> Args {
    serde_json::from_str(line).expect("Invalid JSON input")
}

impl AggregateFunnelRow {
    #[inline(always)]
    fn calculate_funnel_from_user_events(&mut self, args: &Args) {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        args.prop_vals.iter().for_each(|prop_val| self.loop_prop_val(args, prop_val));
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) {
        let mut vars = Vars {
            interval_start_to_entered_timestamps: HashMap::new(),
        };

        let filtered_events = args.value.iter()
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
                if !self.process_event(
                    args,
                    &mut vars,
                    &event,
                    prop_val,
                ) {
                    return
                }
            }
        }


        // At this point, everything left in entered_timestamps is a failure, if it has made it to from_step
        for entered_timestamp in vars.interval_start_to_entered_timestamps.values() {
            if !self.results.contains_key(&(entered_timestamp[0].timestamp as u64)) && entered_timestamp[0].timings.len() > 0 {
                self.results.insert(entered_timestamp[0].timestamp as u64, ResultStruct(entered_timestamp[0].timestamp as u64, -1, prop_val.clone() ));
            }
        }
    }

    #[inline(always)]
    fn process_event(
        &mut self,
        args: &Args,
        vars: &mut Vars,
        event: &Event,
        prop_val: &PropVal,
    ) -> bool {
        for step in event.steps.iter().rev() {
            let mut exclusion = false;
            let step = (if *step < 0 {
                exclusion = true;
                -*step
            } else {
                *step
            }) as usize;

            if step == 1 {
                if !vars.interval_start_to_entered_timestamps.contains_key(&event.interval_start) && !self.results.contains_key(&event.interval_start) {
                    let mut entered_timestamp = vec![DEFAULT_ENTERED_TIMESTAMP.clone(); args.num_steps + 1];
                    entered_timestamp[0] = EnteredTimestamp { timestamp: event.interval_start as f64, timings: if args.from_step == 0 {vec![1.0]} else {vec![]} };
                    entered_timestamp[1] = EnteredTimestamp { timestamp: event.timestamp, timings: vec![event.timestamp] };
                    vars.interval_start_to_entered_timestamps.insert(event.interval_start, entered_timestamp);
                }
            } else {
                for entered_timestamp in vars.interval_start_to_entered_timestamps.values_mut() {
                    let in_match_window = (event.timestamp - entered_timestamp[step - 1].timestamp) <= args.conversion_window_limit as f64;
                    let already_reached_this_step = entered_timestamp[step].timestamp == entered_timestamp[step - 1].timestamp;
                    if in_match_window && !already_reached_this_step {
                        if exclusion {
                            return false;
                        }
                        let is_unmatched_step_attribution = self.breakdown_step.map(|breakdown_step| step == breakdown_step - 1).unwrap_or(false) && *prop_val != event.breakdown;
                        if !is_unmatched_step_attribution {
                            entered_timestamp[step] = EnteredTimestamp {
                                timestamp: entered_timestamp[step - 1].timestamp,
                                timings: {
                                    let mut timings = entered_timestamp[step - 1].timings.clone();
                                    timings.push(event.timestamp);
                                    timings
                                },
                            };
                            // check if we have hit the goal. if we have, remove it from the list and add it to the successful_timestamps
                            if entered_timestamp[args.num_steps].timestamp != 0.0 {
                                self.results.insert(
                                    entered_timestamp[0].timestamp as u64,
                                    ResultStruct(entered_timestamp[0].timestamp as u64, 1, prop_val.clone())
                                );
                            } else if step == args.from_step + 1 {
                                entered_timestamp[0].timings.push(1.0)
                            }
                        }
                    }
                }
            }
        }
        // If a strict funnel, clear all of the steps that we didn't match to
        // If we are processing multiple events, skip this step, because ordering makes it complicated
        if args.funnel_order_type == "strict" {
            for entered_timestamp in vars.interval_start_to_entered_timestamps.values_mut() {
                for i in 1..entered_timestamp.len() {
                    if !event.steps.contains(&(i as i8)) {
                        entered_timestamp[i] = DEFAULT_ENTERED_TIMESTAMP;
                    }
                }
            }
        }
        true
    }
}