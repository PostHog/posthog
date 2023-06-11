insert into posthog_dag.person_distinct_id


with
identified_distinct_ids as (
    select 
        distinct_id,
        team_id
    from events
    where event = '$identify'
    group by distinct_id, team_id
),
all_distinct_ids as (
    select distinct_id, team_id
    from events
    group by distinct_id, team_id
),

-- BLOCK: Merging distinct_ids together
anonymous_merged_users as (
    select
        distinct_id, 
        arrayConcat([distinct_id], arrayCompact(arraySort(groupArray(JSONExtractString(properties, '$anon_distinct_id'))))) distinct_ids,
        team_id
    from
        events
    where
        event = '$identify' and JSONExtractString(properties, '$anon_distinct_id') != ''
    group by distinct_id, team_id
),
aliased_users as (
    select
        distinct_id, 
        arrayConcat([distinct_id], arrayCompact(arraySort(groupArray(JSONExtractString(properties, 'alias'))))) distinct_ids,
        team_id
    from
        events
    where
        event = '$create_alias' and JSONExtractString(properties, 'alias') != ''
    group by distinct_id, team_id
),
aliased_and_anonymous_users as (
    select
        distinct_ids,
        arrayJoin(distinct_ids) as distinct_id,
        team_id
    from anonymous_merged_users
    union all
    select
        distinct_ids,
        arrayJoin(distinct_ids) as distinct_id,
        team_id
    from aliased_users
),
aliased_and_anonymous_users_exploded as (
    select
        distinct_ids,
        arrayJoin(distinct_ids) as distinct_id,
        team_id
    from aliased_and_anonymous_users
),
merge_dangerously_ids as (
    select
        distinct_id as left,
        JSONExtractString(properties, 'alias') as right,
        team_id
    from
        events
    where
        event = '$merge_dangerously'-- and JSONExtractString(properties, '$anon_distinct_id') != ''
),
merge_dangerously as (
    select
        arrayConcat(anon1.distinct_ids, anon2.distinct_ids) distinct_ids,
        merge_dangerously_ids.team_id as team_id
    from merge_dangerously_ids
    inner join aliased_and_anonymous_users anon1 on (left=anon1.distinct_id and merge_dangerously_ids.team_id=anon1.team_id)
    inner join aliased_and_anonymous_users anon2 on (right=anon2.distinct_id and merge_dangerously_ids.team_id=anon2.team_id)
),
all_merged_users as (
    select
        distinct_ids,
        team_id
    from merge_dangerously
    union all

    select
        distinct_ids,
        team_id
    from
        aliased_and_anonymous_users -- all distinct_ids not merged dangerously
    where (distinct_id, team_id) not in (
        select arrayJoin(distinct_ids), team_id from merge_dangerously
    )
),

-- Combine all merged users with any other distinct_id
all_persons as (
    select
        distinct_ids,
        team_id
    from all_merged_users
    union all
    select
        array(distinct_id) as distinct_ids,
        team_id
    from
        all_distinct_ids
    where
        (distinct_id, team_id) not in (select arrayJoin(distinct_ids), team_id from all_merged_users)
),
all_exploded as (
    select 
        team_id, 
        arrayJoin(distinct_ids) as distinct_id,
        -- This ID is not consistent per run
        -- We could use cityHash or something instead to have it consistent
        generateUUIDv4(distinct_ids[1]) as person_id
    from all_persons
)

select 
    team_id,
    distinct_id,
    person_id,
    0 as is_deleted,
    0 as version,
    isNotNull(identified_distinct_ids.distinct_id) as is_identified,
    now() as _timestamp,
    0 as _offset,
    1 as _partition
from all_exploded
left outer join
    identified_distinct_ids ON (identified_distinct_ids.distinct_id=all_exploded.distinct_id and identified_distinct_ids.team_id=all_exploded.team_id)