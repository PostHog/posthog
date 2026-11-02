import { useValues } from 'kea'
import { useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TicketMacroApi } from 'products/conversations/frontend/generated/api.schemas'

import { macroPreview } from './renderMacro'
import { supportMacrosLogic } from './supportMacrosLogic'

export function MacroPicker({
    disabledReason,
    onInsert,
}: {
    disabledReason?: string | JSX.Element
    onInsert: (macro: TicketMacroApi) => void
}): JSX.Element {
    const { macrosSorted, macrosLoading } = useValues(supportMacrosLogic)
    const [query, setQuery] = useState('')
    const needle = query.trim().toLowerCase()
    const matches = macrosSorted.filter((macro) => {
        if (!needle) {
            return true
        }
        return macro.name.toLowerCase().includes(needle) || (macro.shortcut ?? '').includes(needle)
    })

    return (
        <LemonMenu
            placement="top-start"
            closeOnClickInside
            focusBasedKeyboardNavigation={false}
            onVisibilityChange={(visible) => {
                if (!visible) {
                    setQuery('')
                }
            }}
            items={[
                {
                    label: () => (
                        <LemonInput
                            autoFocus
                            fullWidth
                            size="small"
                            placeholder="Search macros"
                            value={query}
                            onChange={setQuery}
                            onClick={(event) => event.stopPropagation()}
                        />
                    ),
                },
                ...matches.slice(0, 8).map((macro) => ({
                    key: macro.id,
                    label: (
                        <span className="flex min-w-0 flex-col items-start">
                            <span className="flex max-w-full items-center gap-2">
                                <span className="truncate">{macro.name}</span>
                                {macro.shortcut ? (
                                    <span className="shrink-0 text-xs text-muted">/{macro.shortcut}</span>
                                ) : null}
                            </span>
                            <span className="max-w-full truncate text-xs text-muted">{macroPreview(macro.body)}</span>
                        </span>
                    ),
                    onClick: () => onInsert(macro),
                    'data-attr': 'support-macro-insert',
                })),
                matches.length === 0
                    ? {
                          label: () => (
                              <span className="block px-2 py-1 text-sm text-muted">
                                  {macrosLoading ? (
                                      'Loading macros'
                                  ) : macrosSorted.length === 0 ? (
                                      <>
                                          No macros yet. Create one in{' '}
                                          <Link to={urls.settings('environment-conversations', 'conversations-macros')}>
                                              Support settings
                                          </Link>
                                          .
                                      </>
                                  ) : (
                                      'No macros match.'
                                  )}
                              </span>
                          ),
                      }
                    : null,
                {
                    label: () => (
                        <Link
                            to={urls.settings('environment-conversations', 'conversations-macros')}
                            className="block px-2 py-1 text-sm"
                        >
                            Manage macros
                        </Link>
                    ),
                },
            ]}
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconDocument />}
                disabledReason={disabledReason}
                data-attr="support-macro-picker"
            >
                Macros
            </LemonButton>
        </LemonMenu>
    )
}
