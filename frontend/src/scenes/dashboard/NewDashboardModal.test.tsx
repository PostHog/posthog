import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { useActions, useMountedLogic, useValues } from 'kea'
import { type ReactNode } from 'react'

import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
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
    LemonInput: ({ value, onChange, ...props }: any) => (
        <input value={value} onChange={(event) => onChange?.(event.target.value)} {...props} />
    ),
    LemonLabel: ({ children }: any) => <label>{children}</label>,
}))

jest.mock('scenes/dashboard/newDashboardLogic', () => ({
    newDashboardLogic: { __mock: 'newDashboardLogic' },
}))

jest.mock('scenes/dashboard/dashboards/templates/dashboardTemplatesLogic', () => ({
    dashboardTemplatesLogic: jest.fn(),
}))

jest.mock('scenes/dashboard/dashboardTemplateVariablesLogic', () => ({
    dashboardTemplateVariablesLogic: { __mock: 'dashboardTemplateVariablesLogic' },
}))

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
const mockedDashboardTemplatesLogic = dashboardTemplatesLogic as jest.Mock

const mockTemplatesLogic = { __mock: 'dashboardTemplatesLogic' }

describe('NewDashboardModal', () => {
    beforeEach(() => {
        jest.clearAllMocks()

        mockedUseMountedLogic.mockReturnValue({ props: {} })
        mockedDashboardTemplatesLogic.mockReturnValue(mockTemplatesLogic)

        mockedUseValues.mockImplementation((logic) => {
            if (logic === newDashboardLogic) {
                return {
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
            }

            if (logic === dashboardTemplateVariablesLogic) {
                return { variables: [] }
            }

            if (logic === mockTemplatesLogic) {
                return { templateFilter: '' }
            }

            return {}
        })

        mockedUseActions.mockImplementation((logic) => {
            if (logic === newDashboardLogic) {
                return {
                    hideNewDashboardModal: jest.fn(),
                    clearActiveDashboardTemplate: jest.fn(),
                    createDashboardFromTemplate: jest.fn(),
                }
            }

            if (logic === mockTemplatesLogic) {
                return {
                    setTemplateFilter: jest.fn(),
                }
            }

            return {}
        })
    })

    it('uses a modal z-index below popovers for variable selection step', () => {
        render(<NewDashboardModal />)

        const dialogPrimitive = document.querySelector('[data-attr="dialog-primitive"]')
        expect(dialogPrimitive).toBeInTheDocument()
        expect(dialogPrimitive?.getAttribute('data-class-name')).toContain('z-[calc(var(--z-popover)-1)]')
    })
})
