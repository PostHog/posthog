-- The activation definition, as data. Keeping it in a one-row seed/model (not hard-coded in every query)
-- means the definition lives in one place and can be versioned. Swap to a dbt seed if you prefer a CSV.
{{ config(materialized='table') }}

select
    'key_action'  as action_event,   -- the validated key action
    3             as min_count,       -- count threshold within the window
    7             as window_days      -- early window from signup
