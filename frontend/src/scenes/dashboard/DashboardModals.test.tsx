import { render } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { DashboardType, QueryBasedInsightModel } from '~/types'

import { dashboardLogic } from './dashboardLogic'
import { DashboardModals } from './DashboardModals'

jest.mock('kea', () => ({
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('kea-router', () => ({
    router: { __mock: 'router' },
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
    ButtonTileCardModal: () => null,
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
    ImageTileModal: () => null,
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
            setTerraformModalOpen: jest.fn(),
            setAddWidgetModalOpen: jest.fn(),
            addWidgetTiles: jest.fn(),
            updateDashboardSuccess: jest.fn(),
        }))
    })

    it('returns to the dashboard when a tile route references a missing tile', () => {
        const dashboard = { id: 5, tiles: [] } as unknown as DashboardType<QueryBasedInsightModel>

        render(<DashboardModals dashboard={dashboard} />)

        expect(push).toHaveBeenCalledWith('/dashboard/5')
    })
})
