insert into posthog_dag.person_distinct_id

with
starting_point as (
    select 
        distinct_id,
        person_id as person_id,
        is_identified,
        team_id,
        1 as in_table
    from posthog_dag.person_distinct_id
    where is_deleted = 0
),

new_distinct_ids as (
    select
        distinct_id,
        toString(cityHash64(distinct_id)) as person_id,
        countIf(event = '$identify') > 0 as is_identified,
        team_id,
        0 as in_table
    from events
    where (distinct_id, team_id) not in (select distinct_id, team_id from starting_point)
    and {timestamp_sql}
    group by distinct_id, team_id
),
all_distinct_ids as (
    select * from starting_point
    union all
    select * from new_distinct_ids
),

merge_anonymous_users as (
    select
        adi.distinct_id as distinct_id, 
        adi.person_id as person_id,
        arrayCompact(arraySort(groupArray(anon_distinct_id))) as discarded_ids,
        adi.team_id as team_id,
        adi.in_table as in_table
    from
        (select distinct_id, JSONExtractString(properties, '$anon_distinct_id') as anon_distinct_id, team_id from events where event = '$identify' and JSONExtractString(properties, '$anon_distinct_id') != '') events
    right outer join all_distinct_ids adi ON (all_distinct_ids.distinct_id=events.distinct_id and all_distinct_ids.team_id=events.team_id)
        
    group by distinct_id, team_id, person_id, in_table
),

aliased_users as (
    select
        merge_anonymous_users.distinct_id as distinct_id, 
        merge_anonymous_users.person_id as person_id,
        arrayCompact(arraySort(arrayConcat(arrayFlatten(groupArray(merge_anonymous_users.discarded_ids)), groupArray(alias)))) as discarded_ids,
        merge_anonymous_users.team_id as team_id,
        merge_anonymous_users.in_table as in_table
    from
        (select
            distinct_id, JSONExtractString(properties, 'alias') alias, team_id
        from events
        where
            event = '$create_alias' and
            JSONExtractString(properties, 'alias') != ''
            -- Don't allow merges on already identified users
            and (team_id, alias) not in (select team_id, distinct_id from all_distinct_ids where is_identified = 1)
            and {timestamp_sql}
    ) events
    right outer join merge_anonymous_users ON (merge_anonymous_users.distinct_id=events.distinct_id and merge_anonymous_users.team_id=events.team_id)

    group by distinct_id, team_id, person_id, in_table
),
merge_dangerously_ids as (
    select
        distinct_id, JSONExtractString(properties, 'alias') alias, team_id
    from events
    where
        event = '$merge_dangerously' and
        JSONExtractString(properties, 'alias') != '' and
        {timestamp_sql}
),
merge_dangerously as (
    select
        aliased_users.distinct_id as distinct_id,
        aliased_users.person_id as person_id,
        -- If we are merging dangerously, grab the discarded ids from the two sides
        -- if only the right join matches, grab the discarded ids from there
        if(
            events.distinct_id != '',
            arrayConcat([alias], left_join.discarded_ids, right_join.discarded_ids),
            aliased_users.discarded_ids
        ) as discarded_ids,
        aliased_users.team_id as team_id,
        aliased_users.in_table as in_table
    from merge_dangerously_ids events

    inner join aliased_users left_join ON (events.distinct_id=left_join.distinct_id and events.team_id=left_join.team_id)
    inner join aliased_users right_join ON (events.alias=right_join.distinct_id and events.team_id=right_join.team_id)
    right outer join aliased_users ON (aliased_users.distinct_id=events.distinct_id and aliased_users.team_id=events.team_id)
    where aliased_users.distinct_id not in (
        select alias from merge_dangerously_ids
    )
),



all_discarded as (
    select
        person_id,
        arrayJoin(arrayFilter(x -> x != '', arrayCompact(arraySort(discarded_ids)))) as distinct_id,
        team_id,
        now() as _timestamp
    from merge_dangerously
    where length(discarded_ids) > 0
)
-- select * from starting_point where team_id = 9
-- select * from merge_dangerously_ids where (distinct_id, team_id) not in (select distinct_id, team_id from all_discarded) and team_id = 54


select 
    team_id,
    distinct_id,
    person_id,
    0 as is_deleted,
    0 as version,
    0 as is_identified,
    now() as _timestamp,
    0 as _offset,
    1 as _partition
from merge_dangerously
where (distinct_id, team_id) not in (select distinct_id, team_id from all_discarded)
and in_table = 0
union all
select 
    team_id,
    distinct_id,
    person_id,
    0 as is_deleted,
    0 as version,
    0 as is_identified,
    now() as _timestamp,
    0 as _offset,
    1 as _partition
from all_discarded 
