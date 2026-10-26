import { useActions, useValues } from 'kea'
import { RefObject } from 'react'

import { IconCode } from '@posthog/icons'

import { ResultMenu, ResultMenuAction } from 'lib/components/ResultMenu/ResultMenu'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { BIDrilldownProps, biDrilldownLogic } from './biDrilldownLogic'

export function BIDrilldownMenu({
    logicProps,
    triggerRef,
}: {
    logicProps: BIDrilldownProps
    triggerRef?: RefObject<HTMLDivElement>
}): JSX.Element | null {
    const { selection, queries, interaction, showRows } = useValues(biDrilldownLogic(logicProps))
    const { close, viewRows, openSqlEditor } = useActions(biDrilldownLogic(logicProps))
    if (!selection || showRows) {
        return null
    }
    const selectedResult =
        selection.labels.map(({ name, value }) => `${name}: ${value}`).join(' · ') || 'All matching rows'
    const actions: ResultMenuAction[] = [
        {
            name: 'View underlying rows',
            icon: <IconTableChart />,
            className: 'ResultMenu__rows',
            disabledReason: !queries ? 'Check the worksheet’s data source and fields before trying again.' : undefined,
            onClick: viewRows,
            to: queries ? urls.sqlEditor({ query: queries.rows }) : undefined,
            inPlace: true,
        },
        {
            name: 'Open in SQL editor',
            icon: <IconCode />,
            className: 'ResultMenu__sql',
            disabledReason: !queries ? 'Check the worksheet’s data source and fields before trying again.' : undefined,
            onClick: openSqlEditor,
            to: queries ? urls.sqlEditor({ query: queries.rows }) : undefined,
        },
    ]

    return (
        <ResultMenu
            triggerRef={triggerRef}
            selectedResult={selectedResult}
            caption={selection.previous ? 'Comparison period' : 'Current period'}
            interaction={interaction}
            actions={actions}
            close={close}
        />
    )
}
