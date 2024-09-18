import { PersonDisplay } from '@posthog/apps-common'
import { useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'

import { PropertyDefinitionType } from '~/types'

import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSidebarPersonTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col overflow-auto bg-bg-3000">
            <div className="font-bold bg-bg-light px-2 border-b py-3">
                <PersonDisplay person={sessionPerson} withIcon noPopover />
            </div>
            <PropertiesTable
                properties={sessionPerson?.properties || []}
                type={PropertyDefinitionType.Person}
                sortProperties
                embedded
            />
        </div>
    )
}
