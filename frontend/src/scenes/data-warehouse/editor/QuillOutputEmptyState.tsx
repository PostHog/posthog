import { IconGraph, IconPlay } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle, Kbd, KbdGroup } from '@posthog/quill'

import { IconTableChart } from 'lib/lemon-ui/icons'

/**
 * What the results pane shows before the first run. It points at the shortcut and nothing else: the
 * setup agent's card that the Lemon pane shows here was closed by about one in five editor users a
 * month, so the quill editor offers connecting sources from the schema panel instead.
 */
export function QuillOutputEmptyState({
    kind,
    singleStatement,
}: {
    kind: 'results' | 'chart'
    singleStatement: boolean
}): JSX.Element {
    return (
        <Empty className="flex-1 border-0" data-attr="sql-editor-output-pane-empty-state">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    {kind === 'chart' ? <IconGraph /> : singleStatement ? <IconPlay /> : <IconTableChart />}
                </EmptyMedia>
                <EmptyTitle>{kind === 'chart' ? 'Run a query to chart it' : 'Run a query to see results'}</EmptyTitle>
                <EmptyDescription>
                    Press{' '}
                    <KbdGroup>
                        <Kbd>⌘</Kbd>
                        <Kbd>↵</Kbd>
                    </KbdGroup>{' '}
                    {singleStatement ? (
                        'to run the query.'
                    ) : (
                        <>
                            to run the statement at your cursor. Separate statements with <code>;</code> to run them one
                            at a time.
                        </>
                    )}
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}
