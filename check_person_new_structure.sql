-- Check posthog_person_new table structure and properties

-- 1. Basic table structure
\d posthog_person_new

-- 2. Check one partition in detail (partition 0)
\d posthog_person_p0

-- 3. Check if id column has identity
SELECT
    attrelid::regclass AS table_name,
    attname AS column_name,
    CASE attidentity
        WHEN 'a' THEN 'ALWAYS'
        WHEN 'd' THEN 'BY DEFAULT'
        ELSE 'NO'
    END AS identity_type
FROM pg_attribute
WHERE attrelid = 'posthog_person_p0'::regclass
AND attname = 'id';

-- 4. Check column default expression
SELECT
    a.attname AS column_name,
    pg_get_expr(d.adbin, d.adrelid) AS default_expression
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
WHERE a.attrelid = 'posthog_person_p0'::regclass
AND a.attname = 'id';

-- 5. Check if sequences exist
SELECT
    schemaname,
    sequencename,
    last_value,
    is_called
FROM pg_sequences
WHERE sequencename LIKE 'posthog_person_p%_id_seq'
ORDER BY sequencename
LIMIT 5;

-- 6. Test insert (will rollback - just to see what happens)
BEGIN;
INSERT INTO posthog_person_new (team_id, created_at, properties, is_identified, uuid)
VALUES (1, NOW(), '{}', false, 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::uuid)
RETURNING id;
ROLLBACK;

-- 7. Compare old vs new table id column
SELECT
    'posthog_person (old)' AS table_name,
    attname AS column_name,
    format_type(atttypid, atttypmod) AS data_type,
    CASE attidentity
        WHEN 'a' THEN 'ALWAYS'
        WHEN 'd' THEN 'BY DEFAULT'
        ELSE 'NO'
    END AS identity,
    pg_get_expr(d.adbin, d.adrelid) AS default_expr
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
WHERE a.attrelid = 'posthog_person'::regclass
AND a.attname = 'id'

UNION ALL

SELECT
    'posthog_person_p0 (new partition)' AS table_name,
    attname AS column_name,
    format_type(atttypid, atttypmod) AS data_type,
    CASE attidentity
        WHEN 'a' THEN 'ALWAYS'
        WHEN 'd' THEN 'BY DEFAULT'
        ELSE 'NO'
    END AS identity,
    pg_get_expr(d.adbin, d.adrelid) AS default_expr
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
WHERE a.attrelid = 'posthog_person_p0'::regclass
AND a.attname = 'id';
