import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { DataColorThemeModal } from './DataColorThemeModal'
import { dataColorThemesConfigLogic } from './dataColorThemesConfigLogic'

export function DataColorThemes(): JSX.Element {
    const { themes, themesLoading } = useValues(dataColorThemesConfigLogic)
    const { selectTheme } = useActions(dataColorThemesConfigLogic)

    return (
        <div className="space-y-4">
            <LemonTable
                loading={themesLoading}
                dataSource={themes || []}
                columns={[{ title: 'Name', dataIndex: 'name', key: 'name' }]}
            />
            <LemonButton type="secondary" onClick={() => selectTheme('new')}>
                Add theme
            </LemonButton>
            <DataColorThemeModal />
        </div>
    )
}
