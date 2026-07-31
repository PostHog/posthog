import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconTableChart } from 'lib/lemon-ui/icons'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode } from '~/queries/schema/schema-general'

import { dataTableLogic } from './dataTableLogic'

interface DataTableOpenEditorProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
}

export function DataTableOpenEditor({ query }: DataTableOpenEditorProps): JSX.Element | null {
    const { response } = useValues(dataTableLogic)
    const disabledReason = getProductAccessDisabledReason({ sceneKey: Scene.Insight, displayLabel: 'Insights' })

    return (
        <LemonButton
            type="secondary"
            icon={<IconTableChart />}
            to={disabledReason ? undefined : urls.insightNew({ query })}
            disabledReason={disabledReason}
            sideAction={
                response && 'hogql' in response && response.hogql
                    ? {
                          dropdown: {
                              overlay: (
                                  <LemonMenuOverlay
                                      items={[
                                          {
                                              label: 'Open in SQL editor',
                                              to: urls.sqlEditor({ query: response.hogql }),
                                              'data-attr': 'open-sql-editor-button',
                                          },
                                      ]}
                                  />
                              ),
                          },
                      }
                    : undefined
            }
            data-attr="open-json-editor-button"
            size="small"
        >
            Open as new insight
        </LemonButton>
    )
}
