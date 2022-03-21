import { v4 } from 'uuid'

import { Base } from './base'
import { Task } from './task'

class TaskMessage {
    constructor(
        readonly headers: Record<string, any>,
        readonly properties: Record<string, any>,
        readonly body: [Array<any>, Record<string, any>, Record<string, any>] | Record<string, any>,
        readonly sentEvent: Record<string, any> | null
    ) {}
}

export class Client extends Base {
    private taskProtocols = {
        1: this.asTaskV1,
        2: this.asTaskV2,
    }

    get createTaskMessage(): (...args: any[]) => TaskMessage {
        return this.taskProtocols[this.conf.TASK_PROTOCOL]
    }

    public async sendTaskMessage(taskName: string, message: TaskMessage): Promise<void> {
        const { headers, properties, body /*, sentEvent */ } = message

        const exchange = ''
        // exchangeType = 'direct';
        // const serializer = 'json';

        await this.broker.publish(body, exchange, this.conf.CELERY_QUEUE, headers, properties)
    }

    public asTaskV2(taskId: string, taskName: string, args?: Array<any>, kwargs?: Record<string, any>): TaskMessage {
        const message: TaskMessage = {
            headers: {
                lang: 'js',
                task: taskName,
                id: taskId,
                /*
        'shadow': shadow,
        'eta': eta,
        'expires': expires,
        'group': group_id,
        'retries': retries,
        'timelimit': [time_limit, soft_time_limit],
        'root_id': root_id,
        'parent_id': parent_id,
        'argsrepr': argsrepr,
        'kwargsrepr': kwargsrepr,
        'origin': origin or anon_nodename()
        */
            },
            properties: {
                correlationId: taskId,
                replyTo: '',
            },
            body: [args, kwargs, {}],
            sentEvent: null,
        }

        return message
    }

    /**
     * create json string representing celery task message. used by Client.publish
     *
     * celery protocol reference: https://docs.celeryproject.org/en/latest/internals/protocol.html
     * celery code: https://github.com/celery/celery/blob/4aefccf8a89bffe9dac9a72f2601db1fa8474f5d/celery/app/amqp.py#L307-L464
     *
     * @function createTaskMessage
     *
     * @returns {String} JSON serialized string of celery task message
     */
    public asTaskV1(taskId: string, taskName: string, args?: Array<any>, kwargs?: Record<string, any>): TaskMessage {
        const message: TaskMessage = {
            headers: {},
            properties: {
                correlationId: taskId,
                replyTo: '',
            },
            body: {
                task: taskName,
                id: taskId,
                args: args,
                kwargs: kwargs,
            },
            sentEvent: null,
        }

        return message
    }

    /**
     * createTask
     * @method Client#createTask
     * @param {string} name for task name
     * @returns {Task} task object
     *
     * @example
     * client.createTask('task.add').delay([1, 2])
     */
    public createTask(name: string): Task {
        return new Task(this, name)
    }

    public async sendTaskAsync(
        taskName: string,
        args?: Array<any>,
        kwargs?: Record<string, any>,
        taskId?: string
    ): Promise<void> {
        taskId = taskId || v4()
        const message = this.createTaskMessage(taskId, taskName, args || [], kwargs || {})
        // run in the background
        await this.sendTaskMessage(taskName, message)
    }

    public sendTask(taskName: string, args?: Array<any>, kwargs?: Record<string, any>, taskId?: string): void {
        void this.sendTaskAsync(taskName, args, kwargs, taskId)
    }
}
