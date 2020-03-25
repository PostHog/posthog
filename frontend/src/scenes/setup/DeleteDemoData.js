import React from 'react'
import { kea, useActions, useValues } from 'kea'
import api from '../../lib/api';

const deleteDemoDataLogic = kea({
    actions: () => ({
        deleteDemoData: true,
        demoDataDeleted: true
    }),
    reducers: ({ actions }) => ({
        isDeleted: [
            false,
            {
                [actions.demoDataDeleted]: () => true
            }
        ]
    }),
    listeners: ({ actions, values }) => ({
        [actions.deleteDemoData]: async () => {
            try {
                const user = await api.get('delete_demo_data')
                actions.demoDataDeleted()
            } catch(error) {
                throw error;
            }
        }
    })
})

export function DeleteDemoData() {

    const { isDeleted } = useValues(deleteDemoDataLogic)
    const { deleteDemoData } = useActions(
        deleteDemoDataLogic
    )
    return <div>
        <button className=' btn btn-outline-danger' onClick={deleteDemoData}>
            Delete demo data
        </button>
        {isDeleted && <p className='text-success'>Demo data deleted!</p>}
    </div>
}