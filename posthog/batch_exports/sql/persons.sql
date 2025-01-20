select
    team_id,
    distinct_id as distinct_id,
    person_id as person_id,
    properties as properties,
    person_distinct_id_version as person_distinct_id_version,
    person_version as person_version,
    created_at as created_at
from
    persons_batch_export
