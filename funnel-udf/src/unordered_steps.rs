use crate::steps::{Args, EnteredTimestamp, Event, Result, DEFAULT_ENTERED_TIMESTAMP};
use crate::PropVal;
use std::collections::VecDeque;
use std::iter::repeat;
use uuid::Uuid;

struct Vars {
    max_step: (usize, EnteredTimestamp),
    events_by_step: Vec<VecDeque<Event>>,
    num_steps_completed: usize,
}

pub struct AggregateFunnelRowUnordered {
    pub breakdown_step: Option<usize>,
    pub results: Vec<Result>,
}

impl AggregateFunnelRowUnordered {
    #[inline(always)]
    pub fn calculate_funnel_from_user_events(&mut self, args: &Args) -> &Vec<Result> {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        args.prop_vals
            .iter()
            .for_each(|prop_val| self.loop_prop_val(args, prop_val));

        &self.results
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) {
        let mut vars = Vars {
            events_by_step: repeat(VecDeque::new()).take(args.num_steps).collect(),
            max_step: (0, DEFAULT_ENTERED_TIMESTAMP.clone()),
            num_steps_completed: 0,
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
            // If we've completed all steps, we can finalize right away
            if vars.max_step.0 == args.num_steps {
                break;
            }
            // Call update_max_step if this is the last event
            if i == all_events.len() - 1 {
                self.update_max_step(&mut vars, event);
            }
        }

        // After processing all events, return the result
        self.results.push(Result(
            vars.max_step.0 as i8 - 1,
            prop_val.clone(),
            vars.max_step
                .1
                .timings
                .windows(2)
                .map(|w| w[1] - w[0])
                .collect(),
            vars.max_step
                .1
                .uuids
                .iter()
                .map(|uuid| vec![*uuid])
                .collect(),
            2_u32.pow(vars.max_step.0 as u32) - 1,
        ));
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

            let has_completed_funnel = vars.num_steps_completed >= args.num_steps;

            // Break if we are in the conversion window and have not completed all the steps.
            if !has_completed_funnel
                && oldest_event.timestamp + args.conversion_window_limit as f64 >= latest_timestamp
            {
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
    }

    #[inline(always)]
    fn update_max_step(&self, vars: &mut Vars, event: &Event) {
        if vars.num_steps_completed > vars.max_step.0 {
            let mut timestamps_with_uuids: Vec<(f64, Uuid)> = vars
                .events_by_step
                .iter()
                .filter_map(|deque| deque.front().map(|e| (e.timestamp, e.uuid)))
                .collect();

            timestamps_with_uuids.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

            let timings = timestamps_with_uuids
                .iter()
                .map(|(t, _)| *t)
                .collect::<Vec<f64>>();
            let uuids = timestamps_with_uuids
                .iter()
                .map(|(_, u)| *u)
                .collect::<Vec<Uuid>>();

            vars.max_step = (
                vars.num_steps_completed,
                EnteredTimestamp {
                    timestamp: event.timestamp,
                    excluded: false,
                    timings,
                    uuids,
                    steps: 0,
                },
            );
        }
    }
}
