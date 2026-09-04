# Where warehouse person and group properties can be used

A warehouse mapping writes its values through the normal ingestion path: `$set` for person targets and
`$groupidentify` for group targets. After the first sync the values are ordinary person or group properties.
There is no separate warehouse property type to select, and no join to write.

So the answer to "where can I use this?" is: anywhere person or group properties already work.

## Surfaces

| Surface                         | How the property appears                                                                                                       | Notes                                                                                                 |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| Feature flag release conditions | A person property filter, or a group property filter on a group-targeted flag                                                  | The most common reason people add these. Read the evaluation caveats below                            |
| Experiments                     | Through the experiment's feature flag                                                                                          | Same caveats as feature flags                                                                         |
| Cohorts                         | A person property condition in a dynamic cohort                                                                                | The cohort recalculates on its own schedule, so a new property takes effect on the next recalculation |
| Insights                        | Filters and breakdowns on person or group properties                                                                           | See the historical events caveat below                                                                |
| Surveys                         | Targeting conditions, through the survey's targeting flag                                                                      | Same caveats as feature flags                                                                         |
| Session replay                  | Filter recordings by person properties                                                                                         |                                                                                                       |
| Web analytics                   | Person property filters where the report supports them                                                                         |                                                                                                       |
| Person and group profile pages  | Listed with the person's or group's other properties                                                                           | The fastest way to confirm a mapping worked for one person                                            |
| HogQL and SQL insights          | `person.properties.<name>` on events, `persons.properties.<name>` on the persons table, `<group>.properties.<name>` for groups |                                                                                                       |
| Workflows and CDP destinations  | Person property conditions and templated values                                                                                | Lets warehouse data steer messaging without an extra lookup                                           |
| Data management > Properties    | The property carries a **Warehouse** tag, with the source table and last sync time in its tooltip                              | Use this to tell warehouse-populated properties apart from SDK-set ones                               |
| Customer analytics              | Group-targeted properties feed account views where the account group type matches                                              | Optional. The mapping itself does not need Customer analytics                                         |

## Caveats worth stating up front

These are the differences a user will otherwise discover as a surprise.

**A person must already exist.** The sync never creates people or groups. A warehouse row whose key does not
resolve is dropped and counted as `skipped_missing_person`. So a customer in the warehouse who has never been
seen by PostHog gets no property, and will not match a flag or cohort until they are.

**Values arrive on a sync cadence, not in real time.** The property changes when the underlying warehouse
table next syncs. For a flag rollout keyed on a warehouse value, that lag is the worst-case delay between the
warehouse changing and the flag flipping.

**Feature flag evaluation has to see the person.** Server-side evaluation that receives only a distinct ID
looks the person up and sees the property. Two setups do not:

- Local evaluation, unless the SDK is given the person properties to evaluate against.
- A client or server call that passes its own `personProperties`, which take precedence over stored ones.

If a flag targeting a warehouse property does not fire, check which of these the caller uses before checking
the sync.

**Historical events and person properties.** By default a project joins current person properties when
querying events, so a newly synced property applies to a person's past events too. Projects moved onto
person-properties-on-events instead read the values frozen on each event at ingestion time, so a new property
only appears on events ingested after it was set. Confirm which mode the project uses before promising that a
breakdown will cover historical data.

**Group properties are per group type.** The `group_type_index` chosen when the definition is created fixes
which group type the properties attach to, and it cannot be changed later. A mapping onto the wrong group
type has to be deleted and recreated.

**Overwrites are silent and repeated.** If a mapped property name matches an existing property, every sync
overwrites it. This is the intended way to let the warehouse own a value, but it also means an SDK writing
the same property fights the sync. Pick one owner per property name.
