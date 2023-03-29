import { useEffect } from 'react'

import api from 'lib/api'

export function Automations(): JSX.Element {
    useEffect(() => {
        const getAutomations = async () => {
            const response = await api.getResponse('/api/projects/1/automations')
            console.log('response: ', response)
        }
        getAutomations()
    }, [])

    return (
        <>
            <h1>Automations</h1>
        </>
    )
}
