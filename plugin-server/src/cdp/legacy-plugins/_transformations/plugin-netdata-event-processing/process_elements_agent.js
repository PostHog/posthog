import {isStringDDMMYYYYHHMM} from "./utils";

export function processElementsAgent(event) {
    // extract properties from elements
    if (event.properties['$elements']) {

        // process each element, last (outermost) first.
        event.properties['$elements'].slice().forEach((element) => {

            // el_data_testid_outer
            if ('attr__data-testid' in element) {
                event.properties['el_data_testid_outer'] = element['attr__data-testid']

                // el_data_testid_outer_0
                if (element['attr__data-testid'].includes('::')) {
                    arr = element['attr__data-testid'].split('::')
                    event.properties['el_data_testid_outer_0'] = arr[0]
                    event.properties['el_data_testid_outer_1'] = arr[1]
                    event.properties['el_data_testid_outer_2'] = arr[2]
                    event.properties['el_data_testid_outer_3'] = arr[3]
                    event.properties['el_data_testid_outer_4'] = arr[4]
                }

            }

            // el_data_ga_outer
            if ('attr__data-ga' in element) {
                event.properties['el_data_ga_outer'] = element['attr__data-ga']

                // el_data_ga_outer_0
                if (element['attr__data-ga'].includes('::')) {
                    arr = element['attr__data-ga'].split('::')
                    event.properties['el_data_ga_outer_0'] = arr[0]
                    event.properties['el_data_ga_outer_1'] = arr[1]
                    event.properties['el_data_ga_outer_2'] = arr[2]
                    event.properties['el_data_ga_outer_3'] = arr[3]
                    event.properties['el_data_ga_outer_4'] = arr[4]
                }

            }

            // el_data_track_outer
            if ('attr__data-track' in element) {
                event.properties['el_data_track_outer'] = element['attr__data-track']

                // el_data_track_outer_0
                if (element['attr__data-track'].includes('::')) {
                    arr = element['attr__data-track'].split('::')
                    event.properties['el_data_track_outer_0'] = arr[0]
                    event.properties['el_data_track_outer_1'] = arr[1]
                    event.properties['el_data_track_outer_2'] = arr[2]
                    event.properties['el_data_track_outer_3'] = arr[3]
                    event.properties['el_data_track_outer_4'] = arr[4]
                }

            }

        })

        // process each element, reverse to use posthog order as preference
        event.properties['$elements'].slice().reverse().forEach((element) => {

            // el_data_testid
            if ('attr__data-testid' in element) {
                event.properties['el_data_testid'] = element['attr__data-testid']

                // el_data_testid_0
                if (element['attr__data-testid'].includes('::')) {
                    arr = element['attr__data-testid'].split('::')
                    event.properties['el_data_testid_0'] = arr[0]
                    event.properties['el_data_testid_1'] = arr[1]
                    event.properties['el_data_testid_2'] = arr[2]
                    event.properties['el_data_testid_3'] = arr[3]
                    event.properties['el_data_testid_4'] = arr[4]
                }

            }

            // el_data_ga
            if ('attr__data-ga' in element) {
                event.properties['el_data_ga'] = element['attr__data-ga']

                // el_data_ga_0
                if (element['attr__data-ga'].includes('::')) {
                    arr = element['attr__data-ga'].split('::')
                    event.properties['el_data_ga_0'] = arr[0]
                    event.properties['el_data_ga_1'] = arr[1]
                    event.properties['el_data_ga_2'] = arr[2]
                    event.properties['el_data_ga_3'] = arr[3]
                    event.properties['el_data_ga_4'] = arr[4]
                }

            }

            // el_data_testid_inner
            if ('attr__data-testid' in element) {
                event.properties['el_data_testid_inner'] = element['attr__data-testid']

                // el_data_testid_inner_0
                if (element['attr__data-testid'].includes('::')) {
                    arr = element['attr__data-testid'].split('::')
                    event.properties['el_data_testid_inner_0'] = arr[0]
                    event.properties['el_data_testid_inner_1'] = arr[1]
                    event.properties['el_data_testid_inner_2'] = arr[2]
                    event.properties['el_data_testid_inner_3'] = arr[3]
                    event.properties['el_data_testid_inner_4'] = arr[4]
                }

            }

            // el_data_ga_inner
            if ('attr__data-ga' in element) {
                event.properties['el_data_ga_inner'] = element['attr__data-ga']

                // el_data_ga_inner_0
                if (element['attr__data-ga'].includes('::')) {
                    arr = element['attr__data-ga'].split('::')
                    event.properties['el_data_ga_inner_0'] = arr[0]
                    event.properties['el_data_ga_inner_1'] = arr[1]
                    event.properties['el_data_ga_inner_2'] = arr[2]
                    event.properties['el_data_ga_inner_3'] = arr[3]
                    event.properties['el_data_ga_inner_4'] = arr[4]
                }

            }

            // el_data_track_inner
            if ('attr__data-track' in element) {
                event.properties['el_data_track_inner'] = element['attr__data-track']

                // el_data_track_inner_0
                if (element['attr__data-track'].includes('::')) {
                    arr = element['attr__data-track'].split('::')
                    event.properties['el_data_track_inner_0'] = arr[0]
                    event.properties['el_data_track_inner_1'] = arr[1]
                    event.properties['el_data_track_inner_2'] = arr[2]
                    event.properties['el_data_track_inner_3'] = arr[3]
                    event.properties['el_data_track_inner_4'] = arr[4]
                }

            }

            // el_id_menu
            if ('attr__href' in element && element['attr__href'] !== null && element['attr__href'].substring(0,5) === '#menu') {
                event.properties['el_href_menu'] = element['attr__href']
                event.properties['el_menu'] = element['attr__href'].split('_submenu')[0].replace('#menu_', '')
                if (element['attr__href'].includes('_submenu_')) {
                    event.properties['el_submenu'] = element['attr__href'].split('_submenu_')[1]
                } else {
                    event.properties['el_submenu'] = ''
                }
            }

            // el_href
            if ('attr__href' in element && element['attr__href'] !== null) {
                event.properties['el_href'] = element['attr__href']
            } else if ('href' in element && element['href'] !== null) {
                event.properties['el_href'] = element['href']
            } else if ('$href' in element && element['$href'] !== null) {
                event.properties['el_href'] = element['$href']
            }

            // el_onclick
            if ('attr__onclick' in element && element['attr__onclick'] !== null) {
                event.properties['el_onclick'] = element['attr__onclick']
            }

            // el_id
            if ('attr__id' in element && element['attr__id'] !== null) {
                event.properties['el_id'] = element['attr__id']
            }

            // el_name
            if ('attr__name' in element && element['attr__name'] !== null) {
                event.properties['el_name'] = element['attr__name']
            }

            // el_title
            if ('attr__title' in element && element['attr__title'] !== null) {
                event.properties['el_title'] = element['attr__title']
            }

            // el_text
            if ('$el_text' in element && element['$el_text'] !== null && element['$el_text'] !== '') {
                event.properties['el_text'] = element['$el_text']

                // el_text_datetime
                if (element['$el_text'].includes('/20') && isStringDDMMYYYYHHMM(element['$el_text'])) {
                    dtStr = element['$el_text']
                    dtStrClean = dtStr.substring(6,10).concat(
                        '-',dtStr.substring(3,5),'-',dtStr.substring(0,2),' ',dtStr.substring(11,16)
                    )
                    event.properties['el_text_datetime'] = dtStrClean
                }

            } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                event.properties['el_text'] = element['text']
            }

            // el_data_netdata
            if ('attr__data-netdata' in element && element['attr__data-netdata'] !== null) {
                event.properties['el_data_netdata'] = element['attr__data-netdata']
            }

            // el_data_target
            if ('attr__data-target' in element && element['attr__data-target'] !== null && element['attr__data-target'] !== '#sidebar') {
                event.properties['el_data_target'] = element['attr__data-target']

                // el_data_target_updatemodal
                if ('attr__data-target' in element && element['attr__data-target'] !== null && element['attr__data-target'] === '#updateModal') {
                    event.properties['el_data_target_updatemodal'] = true
                }

            }

            // el_data_id
            if ('attr__data-id' in element && element['attr__data-id'] !== null) {
                event.properties['el_data_id'] = element['attr__data-id']
            }

            // el_data_original_title
            if ('attr__data-original-title' in element && element['attr__data-original-title'] !== null) {
                event.properties['el_data_original_title'] = element['attr__data-original-title']
            }

            // el_data_toggle
            if ('attr__data-toggle' in element && element['attr__data-toggle'] !== null) {
                event.properties['el_data_toggle'] = element['attr__data-toggle']
            }

            // el_data-legend-position
            if ('attr__data-legend-position' in element && element['attr__data-legend-position'] !== null) {
                event.properties['el_data_legend_position'] = element['attr__data-legend-position']
            }

            // el_aria_controls
            if ('attr__aria-controls' in element && element['attr__aria-controls'] !== null) {
                event.properties['el_aria_controls'] = element['attr__aria-controls']
            }

            // el_aria_labelledby
            if ('attr__aria-labelledby' in element && element['attr__aria-labelledby'] !== null) {
                event.properties['el_aria_labelledby'] = element['attr__aria-labelledby']
            }

            // el_class_netdata_legend_toolbox
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'] === 'netdata-legend-toolbox') {
                event.properties['el_class_netdata_legend_toolbox'] = true
            }

            // el_class_fa_play
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('fa-play')) {
                event.properties['el_class_fa_play'] = true
            }

            // el_class_fa_backward
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('fa-backward')) {
                event.properties['el_class_fa_backward'] = true
            }

            // el_class_fa_forward
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('fa-forward')) {
                event.properties['el_class_fa_forward'] = true
            }

            // el_class_fa_plus
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('fa-plus')) {
                event.properties['el_class_fa_plus'] = true
            }

            // el_class_fa_minus
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('fa-minus')) {
                event.properties['el_class_fa_minus'] = true
            }

            // el_class_fa_sort
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('fa-sort')) {
                event.properties['el_class_fa_sort'] = true
            }

            // el_class_navbar_highlight_content
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('navbar-highlight-content')) {
                event.properties['el_class_navbar_highlight_content'] = true
            }

            // el_class_datepickercontainer
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('DatePickerContainer')) {
                event.properties['el_class_datepickercontainer'] = true
            }

            // el_class_startendcontainer
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('StartEndContainer')) {
                event.properties['el_class_startendcontainer'] = true
            }

            // el_class_pickerbtnarea
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('PickerBtnArea')) {
                event.properties['el_class_pickerbtnarea'] = true
            }

            // el_class_pickerbox
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('PickerBox')) {
                event.properties['el_class_pickerbox'] = true
            }

            // el_class_collapsablesection
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('CollapsableSection')) {
                event.properties['el_class_collapsablesection'] = true
            }

            // el_class_signinbutton
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('SignInButton')) {
                event.properties['el_class_signinbutton'] = true
            }

            // el_class_documentation_container
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('documentation__Container')) {
                event.properties['el_class_documentation_container'] = true
            }

            // el_class_utilitysection
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('UtilitySection')) {
                event.properties['el_class_utilitysection'] = true
            }

            // el_class_success
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('success')) {
                event.properties['el_class_success'] = true
            }

            // el_class_warning
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('warning')) {
                event.properties['el_class_warning'] = true
            }

            // el_class_danger
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('danger')) {
                event.properties['el_class_danger'] = true
            }

            // el_class_info
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'] === 'info') {
                event.properties['el_class_info'] = true
            }

            // el_class_pagination
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('pagination')) {
                event.properties['el_class_pagination'] = true
            }

            // el_class_page_number
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('page-number')) {
                event.properties['el_class_page_number'] = true
            }

            // el_class_export
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('export')) {
                event.properties['el_class_export'] = true
            }

            // el_class_netdata_chartblock_container
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('netdata-chartblock-container')) {
                event.properties['el_class_netdata_chartblock_container'] = true
            }

            // el_class_netdata_reset_button
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('netdata-reset-button')) {
                event.properties['el_class_netdata_reset_button'] = true
            }

            // el_class_netdata_legend_toolbox_button
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('netdata-legend-toolbox-button')) {
                event.properties['el_class_netdata_legend_toolbox_button'] = true
            }

            // el_class_netdata_legend_resize_handler
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('netdata-legend-resize-handler')) {
                event.properties['el_class_netdata_legend_resize_handler'] = true
            }

            // el_class_calendarday
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('CalendarDay')) {
                event.properties['el_class_calendarday'] = true
            }

            // el_class_daypicker
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('DayPicker')) {
                event.properties['el_class_daypicker'] = true
            }

            // el_class_daterangepicker
            if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'].includes('DateRangePicker')) {
                event.properties['el_class_daterangepicker'] = true
            }

            // el_id_date_picker_root
            if ('attr__id' in element && element['attr__id'] !== null && element['attr__id'].includes('date-picker-root')) {
                event.properties['el_id_date_picker_root'] = true
            }

            // el_id_updatemodal
            if ('attr__id' in element && element['attr__id'] !== null && element['attr__id'].includes('updateModal')) {
                event.properties['el_id_updatemodal'] = true
            }

            // el_class
            if ('attr__class' in element && element['attr__class'] !== null) {
                event.properties['el_class'] = element['attr__class']
            }

        })

    }

    return event
}