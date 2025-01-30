export function getInteractionDetailAgent(event) {

    // menu
    if (['menu', 'submenu'].includes(event.properties['interaction_type'])) {

        return event.properties['el_href_menu']

    // chart_toolbox
    } else if (event.properties['interaction_type'] === 'chart_toolbox') {

        if (event.properties.hasOwnProperty('el_class_fa_minus')) {
            return 'zoom_out'
        } else if (event.properties.hasOwnProperty('el_class_fa_plus')) {
            return 'zoom_in'
        } else if (event.properties.hasOwnProperty('el_class_fa_backward')) {
            return 'scroll_backward'
        } else if (event.properties.hasOwnProperty('el_class_fa_forward')) {
            return 'scroll_forward'
        } else if (event.properties.hasOwnProperty('el_class_fa_sort')) {
            return 'resize'
        } else if (event.properties.hasOwnProperty('el_class_fa_play')) {
            return 'play'
        } else {
            return 'other'
        }

    // chart_dim
    } else if (event.properties['interaction_type'] === 'chart_dim') {

        if (
            event.properties.hasOwnProperty('el_id') &&
            event.properties.hasOwnProperty('el_text')
        ) {
            return event.properties['el_data_netdata'].concat('.',event.properties['el_text'])
        } else if (
            event.properties.hasOwnProperty('el_id') &&
            event.properties.hasOwnProperty('el_title')
        ) {
            return event.properties['el_data_netdata'].concat('.',event.properties['el_title'])
        } else {
            return 'other'
        }

    // date_picker
    } else if (event.properties['interaction_type'] === 'date_picker') {

        if (event.properties['el_id'] === 'date-picker-root') {
            return 'open'
        } else if (
            event.properties.hasOwnProperty('el_data_testid') &&
            event.properties['el_data_testid'].startsWith('date-picker')
        ) {
            if (event.properties['el_data_testid'].includes('click-quick-selector')) {
                return event.properties['el_data_testid_1'].concat(' ',event.properties['el_data_testid_3'])
            } else {
                return event.properties['el_data_testid_1']
            }
        } else if (event.properties['el_id'] === 'month_right') {
            return 'month_right'
        } else if (event.properties['el_id'] === 'month_left') {
            return 'month_left'
        } else if (event.properties.hasOwnProperty('el_class_daterangepicker')) {
            return 'date_range'
        } else {
            return 'other'
        }

    // update
    } else if (event.properties['interaction_type'] === 'update') {

        if (event.properties['el_title'] === 'update') {
            return 'open'
        } else if (event.properties['el_text'] === 'Check Now') {
            return 'check'
        } else if (event.properties['el_text'] === 'Close') {
            return 'close'
        } else {
            return 'other'
        }

    // highlight
    } else if (event.properties['interaction_type'] === 'highlight') {

        if (event.properties['el_onclick'] === 'urlOptions.clearHighlight();') {
            return 'clear'
        } else {
            return 'other'
        }

    // settings
    } else if (event.properties['interaction_type'] === 'settings') {

        if (event.properties['el_id'] === 'root') {
            return 'open'
        } else if (event.properties['el_text'] === 'Close') {
            return 'close'
        } else if (event.properties['el_data_toggle'] === 'tab') {
            return 'tab'
        } else if (event.properties['el_data_toggle'] === 'toggle') {
            return 'toggle'
        } else {
            return 'other'
        }

    // alarms
    } else if (event.properties['interaction_type'] === 'alarms') {

        if (
            event.properties.hasOwnProperty('el_href') &&
            event.properties['el_href'].includes('#alarm_all_')
        ) {
            return event.properties['el_text']
        } else if (event.properties.hasOwnProperty('el_class_page_number')) {
            return 'page_number'
        } else if (event.properties['el_id'] === 'root') {
            return 'open'
        } else if (
            event.properties['el_text'] === 'Active' ||
            event.properties['el_id'] === 'alarms_active'
        ) {
            return 'active'
        } else if (event.properties['el_text'] === 'Log') {
            return 'log'
        } else if (event.properties['el_text'] === 'All') {
            return 'all'
        } else if (
            event.properties.hasOwnProperty('el_class_warning') &&
            event.properties.hasOwnProperty('el_text')
        ) {
            if (
                event.properties['el_text'].includes(':') ||
                event.properties['el_text'].includes('%')
            ) {
                return 'warn'
            } else {
                return 'warn__'.concat(event.properties['el_text'])
            }
        } else if (
            event.properties.hasOwnProperty('el_class_success') &&
            event.properties.hasOwnProperty('el_text')
        ) {
            if (
                event.properties['el_text'].includes(':') ||
                event.properties['el_text'].includes('%')
            ) {
                return 'norm'
            } else {
                return 'norm__'.concat(event.properties['el_text'])
            }
        } else if (
            event.properties.hasOwnProperty('el_class_danger') &&
            event.properties.hasOwnProperty('el_text')
        ) {
            if (
                event.properties['el_text'].includes(':') ||
                event.properties['el_text'].includes('%')
            ) {
                return 'crit'
            } else {
                return 'crit__'.concat(event.properties['el_text'])
            }
        } else if (
            event.properties.hasOwnProperty('el_class_info') &&
            event.properties.hasOwnProperty('el_text')
        ) {
            if (
                event.properties['el_text'].includes(':') ||
                event.properties['el_text'].includes('%')
            ) {
                return 'undef'
            } else {
                return 'undef__'.concat(event.properties['el_text'])
            }
        } else if (
            event.properties['el_text'] === 'Close' ||
            event.properties['el_text'] === '×'
        ) {
            return 'close'
        } else if (
            event.properties['el_title'] === 'Refresh' &&
            event.properties['el_id'] === 'alarms_log'
        ) {
            return 'refresh_log'
        } else {
            return 'other'
        }

    // cloud
    } else if (event.properties['interaction_type'] === 'cloud') {

        if (event.properties['el_text'] === 'Sign In to Cloud') {
            return 'sign_in'
        } else {
            return 'other'
        }

    } else {

        return ''

    }
}