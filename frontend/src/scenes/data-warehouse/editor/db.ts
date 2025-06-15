import { openDB } from 'idb'

const dbPromise = openDB('sql-editor', 1, {
    upgrade: (db) => {
        db.createObjectStore('query-tab-state')
    },
})

export const get = async (key: string): Promise<string | null> => {
    return (await dbPromise).get('query-tab-state', key)
}

export const set = async (key: string, val: string): Promise<void> => {
    return void (await dbPromise).put('query-tab-state', val, key)
}

export const del = async (key: string): Promise<void> => {
    return (await dbPromise).delete('query-tab-state', key)
}
