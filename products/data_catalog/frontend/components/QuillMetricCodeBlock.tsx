import { IconCopy } from '@posthog/icons'
import { Button, Card } from '@posthog/quill'

import { CodeLine, Language } from 'lib/components/CodeSnippet'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function QuillMetricCodeBlock({ code, language }: { code: string; language: Language }): JSX.Element {
    return (
        <Card flush className="relative py-0">
            <div className="overflow-x-auto py-2.5 ps-3 pe-10">
                <div className="w-max font-mono text-xs">
                    <CodeLine text={code} language={language} wrapLines={false} />
                </div>
            </div>
            <div className="absolute end-1.5 top-1.5">
                <Button
                    size="icon"
                    aria-label="Copy code"
                    tooltip="Copy code"
                    onClick={() => void copyToClipboard(code, 'code')}
                >
                    <IconCopy />
                </Button>
            </div>
        </Card>
    )
}

export function renderQuillMetricCodeBlock(code: string, language: Language): JSX.Element {
    return <QuillMetricCodeBlock code={code} language={language} />
}
