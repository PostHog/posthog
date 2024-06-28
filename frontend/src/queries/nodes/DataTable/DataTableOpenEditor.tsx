import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema'

import { dataTableLogic } from './dataTableLogic'

interface DataTableOpenEditorProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
}

export function DataTableOpenEditor({ query }: DataTableOpenEditorProps): JSX.Element | null {
    const { response } = useValues(dataTableLogic)

    return (
        <LemonButton
            type="secondary"
            icon={<IconTableChart />}
            to={urls.insightNew(undefined, undefined, JSON.stringify(query))}
            sideAction={
                response?.hogql
                    ? {
                          dropdown: {
                              overlay: (
                                  <LemonMenuOverlay
                                      items={[
                                          {
                                              label: 'Open as direct SQL insight',
                                              to: urls.insightNew(
                                                  undefined,
                                                  undefined,
                                                  JSON.stringify({
                                                      kind: NodeKind.DataTableNode,
                                                      full: true,
                                                      source: { kind: NodeKind.HogQLQuery, query: response.hogql },
                                                  })
                                              ),
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
        >
            Open as new insight
        </LemonButton>
    )
}
