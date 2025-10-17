export const PUBLIC_EMAIL_DOMAINS = [
    'gmail.com',
    'yahoo.com',
    'hotmail.com',
    'outlook.com',
    'aol.com',
    'protonmail.com',
    'icloud.com',
    'mail.com',
    'zoho.com',
    'yandex.com',
    'gmx.com',
    'live.com',
    'mail.ru',
]

export const RAISED_OPTIONS = [
    { label: 'Bootstrapped', value: '0' },
    { label: 'Under $100k', value: '99999' },
    { label: 'From $100k to $500k', value: '499999' },
    { label: 'From $500k to $1m', value: '999999' },
    { label: 'From $1m to $5m', value: '4999999' },
    { label: '$5m or more', value: '5000000' },
]

// Historical values should be fairly accurate (+/- 1 week), future values (Fall 2025+) are estimates based on historical dates
// This should be kept in sync with startups API in billing
export const YC_BATCHES: { batch_name: string; start_date: string; end_date: string }[] = [
    {
        batch_name: 'Fall 2027',
        start_date: '2027-09-29',
        end_date: '2027-12-01',
    },
    {
        batch_name: 'Summer 2027',
        start_date: '2027-07-08',
        end_date: '2027-09-26',
    },
    {
        batch_name: 'Spring 2027',
        start_date: '2027-04-01',
        end_date: '2027-06-17',
    },
    {
        batch_name: 'Winter 2027',
        start_date: '2027-01-06',
        end_date: '2027-03-25',
    },
    {
        batch_name: 'Fall 2026',
        start_date: '2026-09-29',
        end_date: '2026-12-01',
    },
    {
        batch_name: 'Summer 2026',
        start_date: '2026-07-08',
        end_date: '2026-09-26',
    },
    {
        batch_name: 'Spring 2026',
        start_date: '2026-04-01',
        end_date: '2026-06-17',
    },
    {
        batch_name: 'Winter 2026',
        start_date: '2026-01-06',
        end_date: '2026-03-25',
    },
    {
        batch_name: 'Fall 2025',
        start_date: '2025-09-29',
        end_date: '2025-12-01',
    },
    {
        batch_name: 'Summer 2025',
        start_date: '2025-07-08',
        end_date: '2025-09-26',
    },
    {
        batch_name: 'Spring 2025',
        start_date: '2025-04-01',
        end_date: '2025-06-17',
    },
    {
        batch_name: 'Winter 2025',
        start_date: '2025-01-06',
        end_date: '2025-03-25',
    },
    {
        batch_name: 'Fall 2024',
        start_date: '2024-09-29',
        end_date: '2024-12-01',
    },
    {
        batch_name: 'Summer 2024',
        start_date: '2024-07-08',
        end_date: '2024-09-26',
    },
    {
        batch_name: 'Winter 2024',
        start_date: '2024-01-08',
        end_date: '2024-04-03',
    },
    {
        batch_name: 'Summer 2023',
        start_date: '2023-06-12',
        end_date: '2023-09-07',
    },
    {
        batch_name: 'Winter 2023',
        start_date: '2023-01-09',
        end_date: '2023-04-05',
    },
    {
        batch_name: 'Summer 2022',
        start_date: '2022-06-13',
        end_date: '2022-09-07',
    },
    {
        batch_name: 'Winter 2022',
        start_date: '2022-01-10',
        end_date: '2022-03-29',
    },
    {
        batch_name: 'Summer 2021',
        start_date: '2021-06-14',
        end_date: '2021-09-02',
    },
    {
        batch_name: 'Winter 2021',
        start_date: '2021-01-04',
        end_date: '2021-03-23',
    },
]
