import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput, Kbd, KbdGroup } from '@posthog/quill'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { isMac } from 'lib/utils/dom'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

export interface CommandKListSearchProps {
    /** The `is:` filter value that scopes Command K to this list, for example `feature_flag`. */
    type: string
    placeholder: string
    className?: string
    /** The list's own search input, shown outside the today rail or while the new Command K search is off. */
    fallback: JSX.Element
}

export function CommandKListSearch({ type, placeholder, className, fallback }: CommandKListSearchProps): JSX.Element {
    const { todayRailEnabled } = useValues(todayShellLogic)
    const newCommandKSearch = useFeatureFlag('NEW_COMMAND_K_SEARCH')
    const { openCommand } = useActions(commandLogic)

    if (!todayRailEnabled || !newCommandKSearch) {
        return fallback
    }

    const open = (text: string = ''): void => openCommand('list-search', `is:${type} ${text}`)

    return (
        <InputGroup className={className}>
            <InputGroupAddon align="inline-start">
                <IconSearch />
            </InputGroupAddon>
            <InputGroupInput
                readOnly
                placeholder={placeholder}
                aria-label={placeholder}
                data-attr={`command-k-list-search-${type}`}
                onClick={() => open()}
                onKeyDown={(event) => {
                    if (event.metaKey || event.ctrlKey || event.altKey) {
                        return
                    }
                    if (event.key === 'Enter') {
                        event.preventDefault()
                        open()
                    } else if (event.key.length === 1) {
                        event.preventDefault()
                        open(event.key)
                    }
                }}
                onPaste={(event) => {
                    event.preventDefault()
                    open(event.clipboardData.getData('text'))
                }}
            />
            <InputGroupAddon align="inline-end">
                <KbdGroup>
                    <Kbd>{isMac() ? '⌘' : 'Ctrl'}</Kbd>
                    <Kbd>K</Kbd>
                </KbdGroup>
            </InputGroupAddon>
        </InputGroup>
    )
}
