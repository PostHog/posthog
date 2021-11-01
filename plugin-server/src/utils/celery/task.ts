import { Client } from './client'

export class Task {
    client: Client
    name: string

    /**
     * Asynchronous Task
     * @constructor Task
     * @param {Client} client celery client instance
     * @param {string} name celery task name
     */
    constructor(client: Client, name: string) {
        this.client = client
        this.name = name
    }

    /**
     * @method Task#delay
     *
     * @example
     * client.createTask('task.add').delay(1, 2)
     */
    public delay(...args: any[]): void {
        return this.applyAsync([...args])
    }

    public applyAsync(args: Array<any>, kwargs?: Record<string, any>): void {
        if (args && !Array.isArray(args)) {
            throw new Error('args is not array')
        }

        if (kwargs && typeof kwargs !== 'object') {
            throw new Error('kwargs is not object')
        }

        return this.client.sendTask(this.name, args || [], kwargs || {})
    }
}
