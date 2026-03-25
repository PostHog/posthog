import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { editorSizingLogic } from './editorSizingLogic'
import { QueryWindow } from './QueryWindow'
import { sqlEditorLogic } from './sqlEditorLogic'

jest.mock('kea', () => {
    const actual = jest.requireActual('kea')

    return {
        ...actual,
        useActions: jest.fn(),
        useValues: jest.fn(),
    }
})

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(() => false),
}))

jest.mock('lib/components/AppShortcuts/AppShortcut', () => ({
    AppShortcut: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

jest.mock('lib/components/AppShortcuts/shortcuts', () => ({
    keyBinds: { run: 'meta+enter' },
}))

jest.mock('@posthog/icons', () => ({
    IconGear: () => <span />,
    IconInfo: () => <span />,
    IconPlayFilled: () => <span />,
    IconSidebarClose: () => <span />,
}))

jest.mock('@posthog/lemon-ui', () => ({
    LemonDivider: () => null,
}))

jest.mock('lib/lemon-ui/icons', () => ({
    IconCancel: () => <span />,
}))

jest.mock('lib/lemon-ui/LemonButton', () => ({
    LemonButton: ({
        children,
        onClick,
        dataAttr,
        ...props
    }: {
        children?: React.ReactNode
        onClick?: () => void
        dataAttr?: string
    }) => (
        <button onClick={onClick} data-attr={dataAttr} type="button" {...props}>
            {children}
        </button>
    ),
}))

jest.mock('lib/lemon-ui/LemonMenu/LemonMenu', () => ({
    LemonMenu: ({
        children,
        items,
    }: {
        children: React.ReactNode
        items: Array<{ label: string | (() => React.ReactNode) }>
    }) => (
        <div>
            {children}
            {items.map((item, index) => (
                <div key={index}>{typeof item.label === 'function' ? item.label() : item.label}</div>
            ))}
        </div>
    ),
}))

jest.mock('lib/lemon-ui/LemonSwitch', () => ({
    LemonSwitch: ({
        checked,
        onChange,
        label,
    }: {
        checked: boolean
        onChange: (checked: boolean) => void
        label: React.ReactNode
    }) => (
        <label>
            <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
            {label}
        </label>
    ),
}))

jest.mock('lib/lemon-ui/Tooltip', () => ({
    Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

jest.mock('~/layout/panel-layout/ProjectTree/defaultTree', () => ({
    iconForType: jest.fn(() => null),
}))

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitlePanelButton: () => null,
}))

jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({
    dataNodeLogic: {},
}))

jest.mock('./components/FixErrorButton', () => ({
    FixErrorButton: () => null,
}))

jest.mock('./ConnectionSelector', () => ({
    ConnectionSelector: () => null,
}))

jest.mock('./OutputPane', () => ({
    OutputPane: () => null,
}))

jest.mock('./QueryPane', () => ({
    QueryPane: () => null,
}))

jest.mock('./QueryVariablesMenu', () => ({
    QueryVariablesMenu: () => null,
}))

describe('QueryWindow', () => {
    const setSkipHogQLLayer = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()

        ;(useValues as jest.Mock).mockImplementation((logic) => {
            if (logic === sqlEditorLogic) {
                return {
                    queryInput: 'SELECT 1',
                    sourceQuery: {
                        source: {
                            query: 'SELECT 1',
                            connectionId: 'conn-123',
                        },
                    },
                    originalQueryInput: undefined,
                    suggestedQueryInput: undefined,
                    editingView: null,
                    selectedConnectionId: 'conn-123',
                    skipHogQLLayerEnabled: false,
                    finishedLoading: false,
                    metadata: null,
                    isSourceQueryLastRun: false,
                }
            }

            if (logic === editorSizingLogic) {
                return {
                    isDatabaseTreeCollapsed: true,
                }
            }

            if (logic === dataNodeLogic) {
                return {
                    responseLoading: false,
                }
            }

            return {
                featureFlags: {
                    [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
                },
                editorVimModeEnabled: false,
            }
        })

        ;(useActions as jest.Mock).mockImplementation((logic) => {
            if (logic === sqlEditorLogic) {
                return {
                    setQueryInput: jest.fn(),
                    runQuery: jest.fn(),
                    setError: jest.fn(),
                    setMetadata: jest.fn(),
                    setMetadataLoading: jest.fn(),
                    setSuggestedQueryInput: jest.fn(),
                    reportAIQueryPromptOpen: jest.fn(),
                    setSkipHogQLLayer,
                }
            }

            if (logic === dataNodeLogic) {
                return {
                    cancelQuery: jest.fn(),
                }
            }

            return {
                setEditorVimModeEnabled: jest.fn(),
                toggleDatabaseTreeCollapsed: jest.fn(),
            }
        })
    })

    it('routes the skip hogql layer toggle through the logic action', () => {
        render(
            <QueryWindow
                onSetMonacoAndEditor={jest.fn()}
                tabId="test-tab"
                showDatabaseTree={true}
                onShowDatabaseTree={jest.fn()}
            />
        )

        fireEvent.click(screen.getByLabelText('Skip HogQL layer'))

        expect(setSkipHogQLLayer).toHaveBeenCalledWith(true)
    })
})
