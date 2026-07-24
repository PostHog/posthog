import { render, screen } from '@testing-library/react'

import api from 'lib/api'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { AlertType } from '../types'
import { AlertListItem } from './ManageAlertsModal'

describe('ManageAlertsModal', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('includes linked destinations in the alert summary', async () => {
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({
            count: 1,
            results: [{ id: 'destination-1', template_id: 'template-webhook' } as HogFunctionType],
        })
        const alert = {
            id: 'alert-1',
            name: 'Weekly file volume alert',
            enabled: true,
            state: AlertState.NOT_FIRING,
            detector_config: null,
            threshold: {
                configuration: { type: InsightThresholdType.ABSOLUTE, bounds: { lower: 1 } },
            },
            condition: { type: AlertConditionType.ABSOLUTE_VALUE },
            calculation_interval: AlertCalculationInterval.HOURLY,
            subscribed_users: [],
            created_at: '2026-07-24T16:15:51Z',
            created_by: null,
            config: { type: 'TrendsAlertConfig', series_index: 0 },
        } as unknown as AlertType

        render(<AlertListItem alert={alert} onClick={jest.fn()} redesigned />)

        expect(await screen.findByText('1 destination')).toBeTruthy()
    })
})
