export interface CeleryConf {
    CELERY_QUEUE: string
    TASK_PROTOCOL: 1 | 2
}

export function defaultConf(): CeleryConf {
    return {
        CELERY_QUEUE: 'celery',
        TASK_PROTOCOL: 2,
    }
}
