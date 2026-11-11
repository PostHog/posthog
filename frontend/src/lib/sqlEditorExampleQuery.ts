export const SQL_EDITOR_EXAMPLE_QUERY = `select toDate(timestamp) as timestamp, count()
from events
where timestamp >= now() - interval '7 days'
group by timestamp
order by timestamp asc
limit 100`
