import { useEffect } from 'react'

import api from 'lib/api'
import { PageHeader } from 'lib/components/PageHeader'
import { urls } from 'scenes/urls'
import { LemonButton } from '@posthog/lemon-ui'

export function Automations(): JSX.Element {
    useEffect(() => {
        const getAutomations = async (): Promise<void> => {
            const response = await api.getResponse('/api/projects/1/automations')
            console.log('response: ', response)
        }
        getAutomations()
    }, [])

    return (
        <>
            <PageHeader
                title={<div className="flex items-center">Experiments</div>}
                buttons={
                    <LemonButton type="primary" data-attr="create-experiment" to={urls.automation('new')}>
                        New automation
                    </LemonButton>
                }
            />
        </>
    )
}
