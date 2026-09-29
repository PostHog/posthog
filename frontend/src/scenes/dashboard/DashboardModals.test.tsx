import { render } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { ButtonTileCardModal } from 'lib/components/Cards/ButtonTileCard/ButtonTileCardModal'

import type { DashboardType } from '~/types'

import { ImageTileModal } from 'products/dashboards/frontend/components/ImageTile/ImageTileModal'

import { dashboardLogic } from './dashboardLogic'
import { DashboardModals } from './DashboardModals'

jest.mock('kea', () => ({
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('kea-router', () => ({
    router: { __mock: 'router', values: { location: { pathname: '/dashboard/5' }, searchParams: {} } },
}))

jest.mock('./dashboardLogic', () => ({
    dashboardLogic: { __mock: 'dashboardLogic' },
}))

jest.mock('~/models/dashboardsModel', () => ({
    dashboardsModel: { __mock: 'dashboardsModel' },
}))

jest.mock('scenes/userLogic', () => ({
    userLogic: { __mock: 'userLogic' },
}))

jest.mock('@posthog/products-dashboards/frontend/widgets/AddWidgetModal', () => ({
    AddWidgetModal: () => null,
}))

jest.mock('lib/components/Cards/ButtonTileCard/ButtonTileCardModal', () => ({
    ButtonTileCardModal: jest.fn(() => null),
}))

jest.mock('lib/components/Cards/TextCard/TextCardModal', () => ({
    TextCardModal: () => null,
}))

jest.mock('lib/components/Sharing/SharingModal', () => ({
    SharingModal: () => null,
}))

jest.mock('lib/components/TerraformExporter/TerraformExportModal', () => ({
    TerraformExportModal: () => null,
}))

jest.mock('products/dashboards/frontend/components/ImageTile/ImageTileModal', () => ({
    ImageTileModal: jest.fn(() => null),
}))

jest.mock('products/subscriptions/frontend/components/Subscriptions/SubscriptionsModal', () => ({
    SubscriptionsModal: () => null,
}))

jest.mock('./DashboardInsightColorsModal', () => ({
    DashboardInsightColorsModal: () => null,
}))

jest.mock('./DashboardTemplateEditor', () => ({
    DashboardTemplateEditor: () => null,
}))

jest.mock('./DeleteDashboardModal', () => ({
    DeleteDashboardModal: () => null,
}))

jest.mock('./DuplicateDashboardModal', () => ({
    DuplicateDashboardModal: () => null,
}))

const mockedUseActions = useActions as jest.Mock
const mockedUseValues = useValues as jest.Mock
const push = jest.fn()
const closeTileModal = jest.fn()

describe('DashboardModals', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboardMode: null,
                    canEditDashboard: true,
                    showSubscriptions: false,
                    subscriptionId: null,
                    showTextTileModal: true,
                    textTileId: 999,
                    showImageTileModal: false,
                    showButtonTileModal: false,
                    buttonTileId: null,
                    terraformModalOpen: false,
                    addWidgetModalOpen: false,
                    dashboardWidgetsEnabled: false,
                    addWidgetTileLoading: false,
                }
            }
            return { user: null }
        })
        mockedUseActions.mockImplementation(() => ({
            push,
            closeTileModal,
            setTerraformModalOpen: jest.fn(),
            setAddWidgetModalOpen: jest.fn(),
            addWidgetTiles: jest.fn(),
            updateDashboardSuccess: jest.fn(),
        }))
    })

    it('returns to the dashboard when a tile route references a missing tile', () => {
        const dashboard = { id: 5, tiles: [] } as unknown as DashboardType

        render(<DashboardModals dashboard={dashboard} />)

        expect(push).toHaveBeenCalledWith('/dashboard/5')
    })

    it.each([
        ['image', ImageTileModal, 'showImageTileModal'],
        ['button', ButtonTileCardModal, 'showButtonTileModal'],
    ] as const)('closes a new %s modal without navigating', (_type, modal, visibleKey) => {
        mockedUseValues.mockImplementation((logic) =>
            logic === dashboardLogic
                ? {
                      dashboardMode: null,
                      canEditDashboard: true,
                      showSubscriptions: false,
                      subscriptionId: null,
                      showTextTileModal: false,
                      textTileId: null,
                      showImageTileModal: false,
                      showButtonTileModal: false,
                      buttonTileId: null,
                      terraformModalOpen: false,
                      addWidgetModalOpen: false,
                      dashboardWidgetsEnabled: false,
                      addWidgetTileLoading: false,
                      [visibleKey]: true,
                  }
                : { user: null }
        )

        render(<DashboardModals dashboard={{ id: 5, tiles: [] } as unknown as DashboardType} />)
        const modalProps = (modal as jest.Mock).mock.calls[0][0]
        modalProps.onClose()

        expect(closeTileModal).toHaveBeenCalledTimes(1)
        expect(push).not.toHaveBeenCalled()
    })

    it('navigates back from a tile editing route', () => {
        router.values.location.pathname = '/dashboard/5/tiles/1'
        try {
            render(<DashboardModals dashboard={{ id: 5, tiles: [] } as unknown as DashboardType} />)
            const modalProps = (ButtonTileCardModal as jest.Mock).mock.calls[0][0]
            modalProps.onClose()

            expect(push).toHaveBeenCalledWith('/dashboard/5')
            expect(closeTileModal).not.toHaveBeenCalled()
        } finally {
            router.values.location.pathname = '/dashboard/5'
        }
    })
})
