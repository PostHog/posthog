use crate::trends::{Args, EnteredTimestamp, Event, Exclusion, MaxStep, ResultStruct};
use crate::PropVal;
use std::collections::HashMap;
use std::collections::VecDeque;
use std::iter::repeat;
use uuid::Uuid;

pub type ResultsMap = HashMap<u64, ResultStruct>;

struct Vars {
    events_by_step: Vec<VecDeque<Event>>,
    num_steps_completed: usize,
    interval_start_to_interval_data: HashMap<u64, IntervalData>,
}

struct IntervalData {
    max_step: MaxStep,
}

pub struct AggregateFunnelRowUnordered {
    pub breakdown_step: Option<usize>,
}

const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    excluded: false,
};

impl AggregateFunnelRowUnordered {
    #[inline(always)]
    pub fn calculate_funnel_from_user_events(&mut self, args: &Args) -> Vec<ResultStruct> {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        // At the end of the results, we should have
        args.prop_vals
            .iter()
            .flat_map(|prop_val| {
                let results_map = self.loop_prop_val(args, prop_val);
                results_map.into_values().collect::<Vec<ResultStruct>>()
            })
            .collect()
    }

    // At the end of this function, we should have, for each entered timestamp, a ResultsMap
    // The ResultsMap should map an interval timestamp to a ResultStruct
    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) -> ResultsMap {
        let mut vars = Vars {
            events_by_step: repeat(VecDeque::new()).take(args.num_steps).collect(),
            num_steps_completed: 0,
            interval_start_to_interval_data: HashMap::new(),
        };

        // Get all relevant events, both exclusions and non-exclusions
        let all_events: Vec<&Event> = args
            .value
            .iter()
            .filter(|e| {
                if args.breakdown_attribution_type == "all_events" {
                    e.breakdown == *prop_val
                } else {
                    true
                }
            })
            .collect();

        for (i, event) in all_events.iter().enumerate() {
            self.process_event(args, &mut vars, event, prop_val);
            // Call update_max_step if this is the last event
            if i == all_events.len() - 1 {
                self.update_max_step(&mut vars, event);
            }
        }

        vars.interval_start_to_interval_data.iter().filter_map(|(&interval_start, interval_data)| {
            if interval_data.max_step.step >= args.from_step {
                Some((interval_start, ResultStruct(
                    interval_start,
                    if interval_data.max_step.step >= args.num_steps {
                        1
                    } else {
                        -1
                    },
                    prop_val.clone(),
                    interval_data.max_step.event_uuid
                )))
            } else {
                None
            }
        }).collect()
    }

    #[inline(always)]
    fn process_event(&mut self, args: &Args, vars: &mut Vars, event: &Event, prop_val: &PropVal) {
        // Find the latest event timestamp
        let latest_timestamp = event.timestamp;

        // Now we need to look at the oldest event until we're in the conversion window of the newest event
        loop {
            let (oldest_event_index, oldest_event) = vars
                .events_by_step
                .iter()
                .enumerate()
                .filter_map(|(idx, deque)| deque.front().map(|event| (idx, event)))
                .min_by(|(_, a), (_, b)| {
                    a.timestamp
                        .partial_cmp(&b.timestamp)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unzip();

            if oldest_event.is_none() {
                break;
            }

            let oldest_event = oldest_event.unwrap();
            let oldest_event_index = oldest_event_index.unwrap();

            // Now we are in the conversion window so we need to process the new event
            if oldest_event.timestamp + args.conversion_window_limit as f64 >= latest_timestamp {
                break;
            }

            // Update max_step if we've completed more steps than before
            self.update_max_step(vars, event);

            // Here we need to remove the oldest event and potentially decrement the num_steps_completed
            vars.events_by_step[oldest_event_index].pop_front();

            // Decrement num_steps_completed if we no longer have an event in that step
            if vars.events_by_step[oldest_event_index].is_empty() {
                vars.num_steps_completed -= 1;
            }
        }

        // If we hit an exclusion, we clear everything
        let is_exclusion = event.steps.iter().all(|&step| step < 0);

        if is_exclusion {
            vars.events_by_step = repeat(VecDeque::new()).take(args.num_steps).collect();
            vars.num_steps_completed = 0;
            return;
        }

        // Now we process the event as normal

        // Find the step with the minimum timestamp.
        let min_timestamp_step = *event
            .steps
            .iter()
            .min_by_key(|&&step| {
                let step = step as usize;
                ordered_float::OrderedFloat(
                    vars.events_by_step[step - 1]
                        .back()
                        .map(|e| e.timestamp)
                        .unwrap_or(0.0),
                )
            })
            .unwrap() as usize;

        if self.breakdown_step.is_some()
            && vars.num_steps_completed == self.breakdown_step.unwrap()
            && *prop_val != event.breakdown
        {
            // If this step doesn't match the requested attribution, it's not valid
            return;
        }

        if vars.events_by_step[min_timestamp_step - 1].is_empty() {
            vars.num_steps_completed += 1;
        }
        vars.events_by_step[min_timestamp_step - 1].push_back(event.clone());
        // Print the length of each entry in events_by_step
        println!();
        for (i, events) in vars.events_by_step.iter().enumerate() {
            for (j, event) in events.iter().enumerate() {
                println!("Step {}, Event {}: {:?}", i + 1, j + 1, event);
            }
        }
    }

    #[inline(always)]
    fn update_max_step(&self, vars: &mut Vars, event: &Event) {
        let interval_start = event.interval_start;

        let greater_than_max_step = vars
            .interval_start_to_interval_data
            .get(&interval_start)
            .map_or(true, |interval_data| {
                vars.num_steps_completed > interval_data.max_step.step
            });

        if greater_than_max_step {
            vars.interval_start_to_interval_data.insert(
                interval_start,
                IntervalData {
                    max_step: MaxStep {
                        step: vars.num_steps_completed,
                        timestamp: event.timestamp,
                        excluded: Exclusion::Not,
                        event_uuid: event.uuid,
                    },
                },
            );
        }
    }
}
