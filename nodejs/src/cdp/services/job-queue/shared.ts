import { Histogram } from 'prom-client'

export const cdpJobSizeKb = new Histogram({
    name: 'cdp_job_size_kb',
    help: 'The size in kb of the jobs we are processing',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})
