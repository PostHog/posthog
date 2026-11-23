select properties.account_id as account_id, max(timestamp) as last_checkout
from events
where event = 'checkout_completed'
group by account_id
having last_checkout < now() - interval 60 day
