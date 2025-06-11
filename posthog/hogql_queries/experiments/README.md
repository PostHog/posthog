# Experiment query runner documentation

## Funnel evaluation expression

As the query construction to meet the `aggregate_funnel_array` input format is somewhat complex,
this explains the different parts in more detail.

### 1. Step condition construction

```sql
multiply(1, if(equals(metric_events.event, '$pageview'), 1, 0)),
multiply(2, if(equals(metric_events.event, 'checkout started'), 1, 0)),
multiply(3, if(equals(metric_events.event, 'checkout completed'), 1, 0)),
```

-   **Purpose**: Creates numeric step identifiers for each event
-   **Logic**: If event matches the step condition, return the step number (1, 2, 3), otherwise 0
-   **Result**: Each event gets tagged with which funnel steps it satisfies

### 2. Events array construction

```sql
arraySort(t -> t.1, groupArray(tuple(
    timestamp_float,                   -- Sort key: timestamp
    uuid,                              -- Event identifier
    array(''),                         -- Breakdown value (empty = no breakdown)
    arrayFilter(x -> x != 0, [...])    -- Step numbers this event matches
)))
```

-   **Purpose**: Creates the main input array for the UDF
-   **Sorting**: Events are sorted by timestamp (t.1) to ensure chronological order
-   **Filtering**: `arrayFilter(x -> x != 0, [...])` removes zeros, leaving only actual step numbers
-   **Example result**: `[(1704110400.0, uuid1, '', [1]), (1704110700.0, uuid2, '', [2])]`

### 3. UDF function call

```sql
aggregate_funnel_array(
    3,                    -- Number of steps in funnel
    3600,                 -- Conversion window: 1 hour
    'first_touch',        -- Attribution: use first occurrence of breakdown
    'ordered',            -- Order: events must happen in sequence
    array(array('')),     -- Breakdown values, empty -> no breakdown
    events_array          -- Preprocessed events data as above
)
```

-   **Purpose**: Performs the funnel analysis logic
-   **Window**: 3600 seconds = 1 hour maximum between first and last step
-   **Attribution**: Which attribution type to use. Only relevant if using breakdowns. We don't.
-   **Ordering**: 'ordered' means step 2 must come after step 1, step 3 after step 2
-   **Returns**: Array of tuples with results for each user

### 4. Result output

The UDF returns tuples with this structure:

-   **`step_reached`**: Highest step completed (0-indexed, so 2 = completed all 3 steps)
-   **`breakdown_values`**: Array of breakdown property values (empty in our case)
-   **`conversion_times`**: Array of seconds between steps [step1→step2, step2→step3]
-   **`event_uuids`**: Arrays of UUIDs for events used in each step

### 5. Result evaluation

Finally, we evaluate wether the user completed the full funnel (return 1) or not (return 0).
`aggregate_funnel_array` returns an array of tuples for each user (One for each breakdown value?
We don't care about breakdown values so there will only be one element in the array). We then
filter the array first to only keep the element if the funnel was completed,
i.e `step_reached >= num_steps - 1` (`step_reached` is 0-indexd).
Finally, if the list is not empty (`length > 0`), we return 1, otherwise 0.
