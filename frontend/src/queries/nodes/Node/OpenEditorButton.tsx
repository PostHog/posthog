import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { Node } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { IconQueryEditor, IconQueryEye } from 'lib/lemon-ui/icons'

export interface OpenEditorButtonProps extends LemonButtonProps {
    query: Node | null
    hogql?: string | null
}

export function OpenEditorButton({ query, hogql, ...props }: OpenEditorButtonProps): JSX.Element {
    return (
        <>
            <LemonButton
                data-attr={'open-json-editor-button'}
                type="secondary"
                status="primary-alt"
                to={query ? urls.insightNew(undefined, undefined, JSON.stringify(query)) : undefined}
                icon={<IconQueryEditor />}
                tooltip={'Open as a new insight'}
                {...props}
            />
            {hogql ? (
                <LemonButton
                    data-attr={'open-hogql-editor-button'}
                    type="secondary"
                    status="primary-alt"
                    to={
                        query
                            ? urls.insightNew(
                                  undefined,
                                  undefined,
                                  JSON.stringify({
                                      kind: 'DataTableNode',
                                      full: true,
                                      source: { kind: 'HogQLQuery', query: hogql },
                                  })
                              )
                            : undefined
                    }
                    icon={<IconQueryEye />}
                    tooltip={'Edit SQL query'}
                    {...props}
                />
            ) : null}
        </>
    )
}
