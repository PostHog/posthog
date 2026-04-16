import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { useActions, useMountedLogic, useValues } from 'kea'
import { type ReactNode } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { NewDashboardModal } from './NewDashboardModal'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
    useMountedLogic: jest.fn(),
}))

jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    LemonInput: ({ value, onChange, fullWidth: _fullWidth, ...props }: any) => (
        <input value={value} onChange={(event) => onChange?.(event.target.value)} {...props} />
    ),
}))

jest.mock('scenes/dashboard/newDashboardLogic', () => ({
    newDashboardLogic: { __mock: 'newDashboardLogic' },
}))

jest.mock('scenes/dashboard/dashboards/templates/dashboardTemplatesLogic', () => ({
    dashboardTemplatesLogic: jest.fn(),
}))

jest.mock('scenes/dashboard/dashboards/templates/dashboardTemplateChooserLogic', () => {
    const actual = jest.requireActual<
        typeof import('scenes/dashboard/dashboards/templates/dashboardTemplateChooserLogic')
    >('scenes/dashboard/dashboards/templates/dashboardTemplateChooserLogic')
    return {
        ...actual,
        dashboardTemplateChooserLogic: jest.fn(),
    }
})

jest.mock('./dashboards/templates/DashboardTemplateChooser', () => ({
    DashboardTemplateChooser: () => <div data-attr="dashboard-template-chooser" />,
}))

jest.mock('./DashboardTemplateVariables', () => ({
    DashboardTemplateVariables: () => <div data-attr="dashboard-template-variables" />,
}))

jest.mock('lib/ui/DialogPrimitive/DialogPrimitive', () => ({
    DialogPrimitive: ({ children, className }: { children: ReactNode; className?: string }) => (
        <div data-attr="dialog-primitive" data-class-name={className}>
            {children}
        </div>
    ),
    DialogPrimitiveTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DialogClose: () => <button type="button">Close</button>,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseMountedLogic = useMountedLogic as jest.Mock
const mockedDashboardTemplatesLogic = jest.requireMock<{
    dashboardTemplatesLogic: jest.Mock
}>('scenes/dashboard/dashboards/templates/dashboardTemplatesLogic').dashboardTemplatesLogic
const mockedDashboardTemplateChooserLogic = jest.requireMock<{
    dashboardTemplateChooserLogic: jest.Mock
}>('scenes/dashboard/dashboards/templates/dashboardTemplateChooserLogic').dashboardTemplateChooserLogic

const mockTemplatesLogic = { __mock: 'dashboardTemplatesLogic' as const }
const mockChooserLogic = { __mock: 'dashboardTemplateChooserLogic' as const }

function logicPath(logic: unknown): string | undefined {
    try {
        return (logic as { pathString?: string } | null | undefined)?.pathString
    } catch {
        return undefined
    }
}

function isNewDashboardLogicRef(logic: unknown): boolean {
    const tag = (logic as { __mock?: string } | null | undefined)?.__mock
    return logic === newDashboardLogic || tag === 'newDashboardLogic'
}

function isDashboardTemplateVariablesLogicRef(logic: unknown): boolean {
    const tag = (logic as { __mock?: string } | null | undefined)?.__mock
    return logic === dashboardTemplateVariablesLogic || tag === 'dashboardTemplateVariablesLogic'
}

function isFeatureFlagLogicRef(logic: unknown): boolean {
    return logic === featureFlagLogic || logicPath(logic)?.includes('featureFlagLogic') === true
}

function isMockTemplatesLogicRef(logic: unknown): boolean {
    const tag = (logic as { __mock?: string } | null | undefined)?.__mock
    return logic === mockTemplatesLogic || tag === 'dashboardTemplatesLogic'
}

function isMockChooserLogicRef(logic: unknown): boolean {
    const tag = (logic as { __mock?: string } | null | undefined)?.__mock
    return logic === mockChooserLogic || tag === 'dashboardTemplateChooserLogic'
}

const Z_INDEX_CLASS = 'z-[calc(var(--z-popover)-1)]'

describe('NewDashboardModal', () => {
    let newDashboardValues: Record<string, unknown>

    beforeEach(() => {
        jest.clearAllMocks()
        mockedUseValues.mockReset()
        mockedUseActions.mockReset()

        newDashboardValues = {
            newDashboardModalVisible: true,
            activeDashboardTemplate: {
                template_name: 'Product analytics',
                variables: [
                    {
                        id: 'VARIABLE_1',
                        name: 'Daily active user event',
                        default: { id: '$pageview' },
                        description: 'Event used for DAU',
                        required: true,
                        type: 'event',
                    },
                ],
            },
            variableSelectModalVisible: false,
        }

        mockedUseMountedLogic.mockReturnValue({ props: {} })
        mockedDashboardTemplatesLogic.mockReturnValue(mockTemplatesLogic)
        mockedDashboardTemplateChooserLogic.mockReturnValue(mockChooserLogic)

        mockedUseValues.mockImplementation((logic: unknown) => {
            // Match concrete mocks before featureFlagLogicRef — Kea throws when reading pathString on unmounted logics.
            if (isNewDashboardLogicRef(logic)) {
                return newDashboardValues
            }

            if (isDashboardTemplateVariablesLogicRef(logic)) {
                return { variables: [] }
            }

            if (isMockTemplatesLogicRef(logic)) {
                return { templateFilter: '' }
            }

            if (isMockChooserLogicRef(logic)) {
                return { isLoading: false }
            }

            if (isFeatureFlagLogicRef(logic)) {
                return { featureFlags: {} }
            }

            throw new Error(
                `NewDashboardModal.test: unhandled useValues(${logicPath(logic) ?? (logic as { __mock?: string })?.__mock ?? typeof logic}). Extend is*Ref helpers or add a branch.`
            )
        })

        mockedUseActions.mockImplementation((logic: unknown) => {
            if (isNewDashboardLogicRef(logic)) {
                return {
                    hideNewDashboardModal: jest.fn(),
                    clearActiveDashboardTemplate: jest.fn(),
                    createDashboardFromTemplate: jest.fn(),
                }
            }

            if (isMockTemplatesLogicRef(logic)) {
                return {
                    setTemplateFilter: jest.fn(),
                }
            }

            if (isMockChooserLogicRef(logic)) {
                return {
                    blankTileClicked: jest.fn(),
                }
            }

            throw new Error(
                `NewDashboardModal.test: unhandled useActions(${logicPath(logic) ?? (logic as { __mock?: string })?.__mock ?? typeof logic}). Extend is*Ref helpers or add a branch.`
            )
        })
    })

    afterEach(() => {
        cleanup()
    })

    const expectDialogStacking = (): void => {
        const dialogPrimitive = document.querySelector('[data-attr="dialog-primitive"]')
        expect(dialogPrimitive).toBeInTheDocument()
        const className = dialogPrimitive?.getAttribute('data-class-name') ?? ''
        expect(className).toContain(Z_INDEX_CLASS)
    }

    it('keeps template variable pickers above the modal chrome on the variable step', () => {
        render(<NewDashboardModal />)
        expectDialogStacking()
        expect(document.querySelector('[data-attr="dashboard-template-variables"]')).toBeInTheDocument()
    })

    it('still keeps pickers and portaled menus above the modal on the template picker step', () => {
        newDashboardValues = {
            newDashboardModalVisible: true,
            activeDashboardTemplate: null,
            variableSelectModalVisible: false,
        }

        render(<NewDashboardModal />)
        expectDialogStacking()
        expect(document.querySelector('[data-attr="dashboard-template-chooser"]')).toBeInTheDocument()
    })
})
