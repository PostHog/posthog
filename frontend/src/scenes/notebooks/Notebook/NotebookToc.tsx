import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { notebookLogic } from './notebookLogic'

export function NotebookToc(): JSX.Element {
    const { tableOfContents } = useValues(notebookLogic)

    return (
        <div className="NotebookColumn__content-height">
            <ul className="space-y-px">
                {tableOfContents.map((x, i) => (
                    <li key={i} className={`ml-${x.level * 2}`}>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={() => {
                                alert('todo!')
                            }}
                            fullWidth
                        >
                            {x.title}
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </div>
    )
}
