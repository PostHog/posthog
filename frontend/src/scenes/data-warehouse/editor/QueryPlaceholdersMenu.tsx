import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem } from '@posthog/lemon-ui'

import { sqlEditorLogic } from './sqlEditorLogic'

export function QueryPlaceholdersMenu(): JSX.Element | null {
    const { placeholders } = useValues(sqlEditorLogic)
    const { insertTextAtCursor } = useActions(sqlEditorLogic)

    if (placeholders.length === 0) {
        return null
    }

    const items: LemonMenuItem[] = placeholders.map((placeholder) => ({
        key: placeholder.name,
        custom: true,
        label: (
            <span className="flex flex-col gap-0.5 py-0.5">
                <code className="text-xs">{`{${placeholder.name}}`}</code>
                <span className="text-xs text-secondary">{placeholder.description}</span>
                <span className="text-xxs text-muted-alt">Preview value: {placeholder.previewValue}</span>
            </span>
        ),
        onClick: () => insertTextAtCursor(`{${placeholder.name}}`),
    }))

    return (
        <LemonMenu items={[{ title: 'Insert into query', items }]} placement="bottom-start">
            <LemonButton type="secondary" size="small" icon={<IconClock />} data-attr="sql-editor-placeholders-button">
                Placeholders
            </LemonButton>
        </LemonMenu>
    )
}
