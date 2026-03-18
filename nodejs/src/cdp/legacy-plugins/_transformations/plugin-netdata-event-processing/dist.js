function cleanPropertyName(k) {
    return (
        k
            // convert to lower case
            .toLowerCase()
            // remove leading slash
            .replace(/^\//, '')
            // replace all slashes and dots with _
            .replace(/\/|\.|-| /g, '_')
    )
}

function isStringDDMMYYYYHHMM(dt) {
    var reDate = /^((0?[1-9]|[12][0-9]|3[01])[- /.](0?[1-9]|1[012])[- /.](19|20)?[0-9]{2}[ ][012][0-9][:][0-9]{2})*$/
    return reDate.test(dt)
}

function isDemo(url) {
    if (
        url.includes('://london.my-netdata.io') ||
        url.includes('://london3.my-netdata.io') ||
        url.includes('://cdn77.my-netdata.io') ||
        url.includes('://octopuscs.my-netdata.io') ||
        url.includes('://bangalore.my-netdata.io') ||
        url.includes('://frankfurt.my-netdata.io') ||
        url.includes('://newyork.my-netdata.io') ||
        url.includes('://sanfrancisco.my-netdata.io') ||
        url.includes('://singapore.my-netdata.io') ||
        url.includes('://toronto.my-netdata.io')
    ) {
        return true
    } else {
        return false
    }
}

function splitPathName(event) {
    if (event.properties['$pathname']) {
        event.properties['$pathname'].split('/').forEach((pathname, index) => {
            if (pathname !== '' && pathname !== null) {
                event.properties[`pathname_${index}`] = pathname
            }
        })
    }
    return event
}

function processElementsAgent(event) {
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
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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
                if (
                    'attr__href' in element &&
                    element['attr__href'] !== null &&
                    element['attr__href'].substring(0, 5) === '#menu'
                ) {
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
                        dtStrClean = dtStr
                            .substring(6, 10)
                            .concat(
                                '-',
                                dtStr.substring(3, 5),
                                '-',
                                dtStr.substring(0, 2),
                                ' ',
                                dtStr.substring(11, 16)
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
                if (
                    'attr__data-target' in element &&
                    element['attr__data-target'] !== null &&
                    element['attr__data-target'] !== '#sidebar'
                ) {
                    event.properties['el_data_target'] = element['attr__data-target']

                    // el_data_target_updatemodal
                    if (
                        'attr__data-target' in element &&
                        element['attr__data-target'] !== null &&
                        element['attr__data-target'] === '#updateModal'
                    ) {
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
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'] === 'netdata-legend-toolbox'
                ) {
                    event.properties['el_class_netdata_legend_toolbox'] = true
                }

                // el_class_fa_play
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('fa-play')
                ) {
                    event.properties['el_class_fa_play'] = true
                }

                // el_class_fa_backward
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('fa-backward')
                ) {
                    event.properties['el_class_fa_backward'] = true
                }

                // el_class_fa_forward
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('fa-forward')
                ) {
                    event.properties['el_class_fa_forward'] = true
                }

                // el_class_fa_plus
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('fa-plus')
                ) {
                    event.properties['el_class_fa_plus'] = true
                }

                // el_class_fa_minus
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('fa-minus')
                ) {
                    event.properties['el_class_fa_minus'] = true
                }

                // el_class_fa_sort
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('fa-sort')
                ) {
                    event.properties['el_class_fa_sort'] = true
                }

                // el_class_navbar_highlight_content
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('navbar-highlight-content')
                ) {
                    event.properties['el_class_navbar_highlight_content'] = true
                }

                // el_class_datepickercontainer
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('DatePickerContainer')
                ) {
                    event.properties['el_class_datepickercontainer'] = true
                }

                // el_class_startendcontainer
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('StartEndContainer')
                ) {
                    event.properties['el_class_startendcontainer'] = true
                }

                // el_class_pickerbtnarea
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('PickerBtnArea')
                ) {
                    event.properties['el_class_pickerbtnarea'] = true
                }

                // el_class_pickerbox
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('PickerBox')
                ) {
                    event.properties['el_class_pickerbox'] = true
                }

                // el_class_collapsablesection
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('CollapsableSection')
                ) {
                    event.properties['el_class_collapsablesection'] = true
                }

                // el_class_signinbutton
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('SignInButton')
                ) {
                    event.properties['el_class_signinbutton'] = true
                }

                // el_class_documentation_container
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('documentation__Container')
                ) {
                    event.properties['el_class_documentation_container'] = true
                }

                // el_class_utilitysection
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('UtilitySection')
                ) {
                    event.properties['el_class_utilitysection'] = true
                }

                // el_class_success
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('success')
                ) {
                    event.properties['el_class_success'] = true
                }

                // el_class_warning
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('warning')
                ) {
                    event.properties['el_class_warning'] = true
                }

                // el_class_danger
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('danger')
                ) {
                    event.properties['el_class_danger'] = true
                }

                // el_class_info
                if ('attr__class' in element && element['attr__class'] !== null && element['attr__class'] === 'info') {
                    event.properties['el_class_info'] = true
                }

                // el_class_pagination
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('pagination')
                ) {
                    event.properties['el_class_pagination'] = true
                }

                // el_class_page_number
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('page-number')
                ) {
                    event.properties['el_class_page_number'] = true
                }

                // el_class_export
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('export')
                ) {
                    event.properties['el_class_export'] = true
                }

                // el_class_netdata_chartblock_container
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('netdata-chartblock-container')
                ) {
                    event.properties['el_class_netdata_chartblock_container'] = true
                }

                // el_class_netdata_reset_button
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('netdata-reset-button')
                ) {
                    event.properties['el_class_netdata_reset_button'] = true
                }

                // el_class_netdata_legend_toolbox_button
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('netdata-legend-toolbox-button')
                ) {
                    event.properties['el_class_netdata_legend_toolbox_button'] = true
                }

                // el_class_netdata_legend_resize_handler
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('netdata-legend-resize-handler')
                ) {
                    event.properties['el_class_netdata_legend_resize_handler'] = true
                }

                // el_class_calendarday
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('CalendarDay')
                ) {
                    event.properties['el_class_calendarday'] = true
                }

                // el_class_daypicker
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('DayPicker')
                ) {
                    event.properties['el_class_daypicker'] = true
                }

                // el_class_daterangepicker
                if (
                    'attr__class' in element &&
                    element['attr__class'] !== null &&
                    element['attr__class'].includes('DateRangePicker')
                ) {
                    event.properties['el_class_daterangepicker'] = true
                }

                // el_id_date_picker_root
                if (
                    'attr__id' in element &&
                    element['attr__id'] !== null &&
                    element['attr__id'].includes('date-picker-root')
                ) {
                    event.properties['el_id_date_picker_root'] = true
                }

                // el_id_updatemodal
                if (
                    'attr__id' in element &&
                    element['attr__id'] !== null &&
                    element['attr__id'].includes('updateModal')
                ) {
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

function getInteractionTypeAgent(event) {
    if (['$pageview', '$pageleave', '$identify', 'agent backend'].includes(event.event)) {
        return event.event.replace('$', '').replace(' ', '_')

        // menu
    } else if (event.properties.hasOwnProperty('el_href_menu')) {
        return event.properties['el_href_menu'].includes('submenu') ? 'submenu' : 'menu'

        // chart_toolbox
    } else if (
        event.properties.hasOwnProperty('el_class_netdata_legend_resize_handler') ||
        event.properties.hasOwnProperty('el_class_netdata_legend_toolbox')
    ) {
        return 'chart_toolbox'

        // chart_dim
    } else if (
        event.properties.hasOwnProperty('el_data_netdata') &&
        event.properties.hasOwnProperty('el_id') &&
        (event.properties.hasOwnProperty('el_text') || event.properties.hasOwnProperty('el_title')) &&
        event.properties['el_id'].startsWith('chart_')
    ) {
        return 'chart_dim'

        // date_picker
    } else if (
        event.properties['el_id'] === 'date-picker-root' ||
        (event.properties.hasOwnProperty('el_data_testid') &&
            event.properties['el_data_testid'].startsWith('date-picker')) ||
        event.properties.hasOwnProperty('el_class_daterangepicker')
    ) {
        return 'date_picker'

        // hamburger
    } else if (
        event.properties.hasOwnProperty('el_class_collapsablesection') ||
        event.properties['el_title'] === 'hamburger'
    ) {
        return 'hamburger'

        // update
    } else if (
        event.properties.hasOwnProperty('el_data_target_updatemodal') ||
        event.properties.hasOwnProperty('el_id_updatemodal')
    ) {
        return 'update'

        // help
    } else if (
        ['Need Help?', 'question'].includes(event.properties['el_title']) ||
        event.properties['el_data_testid'] === 'documentation-help-close' ||
        event.properties.hasOwnProperty('el_class_documentation_container')
    ) {
        return 'help'

        // load_snapshot
    } else if (
        event.properties['el_data_target'] === '#loadSnapshotModal' ||
        event.properties['el_id'] === 'loadSnapshotDragAndDrop' ||
        event.properties['el_id'] === 'loadSnapshotSelectFiles' ||
        event.properties['el_id'] === 'loadSnapshotModal'
    ) {
        return 'load_snapshot'

        // save_snapshot
    } else if (
        event.properties['el_data_target'] === '#saveSnapshotModal' ||
        event.properties['el_id'] === 'saveSnapshotResolutionSlider' ||
        event.properties['el_id'] === 'saveSnapshotExport' ||
        event.properties['el_id'] === 'saveSnapshotModal' ||
        event.properties['el_id'] === 'hiddenDownloadLinks'
    ) {
        return 'save_snapshot'

        // print
    } else if (
        event.properties['el_data_target'] === '#printPreflightModal' ||
        event.properties['el_onclick'] === 'return printPreflight(),!1'
    ) {
        return 'print'

        // alarms
    } else if (
        event.properties['el_data_target'] === '#alarmsModal' ||
        ['#alarms_all', '#alarms_log', '#alarms_active'].includes(event.properties['el_href']) ||
        event.properties['el_id'] === 'alarms_log_table' ||
        event.properties['el_id'] === 'alarms_log' ||
        event.properties['el_id'] === 'alarmsModal' ||
        event.properties['el_aria_labelledby'] === 'alarmsModalLabel'
    ) {
        return 'alarms'

        // settings
    } else if (
        event.properties['el_data_target'] === '#optionsModal' ||
        event.properties['el_id'] === 'optionsModal' ||
        event.properties['el_aria_labelledby'] === 'optionsModalLabel'
    ) {
        return 'settings'

        // cloud
    } else if (event.properties.hasOwnProperty('el_class_signinbutton')) {
        return 'cloud'

        // highlight
    } else if (event.properties['el_id'] === 'navbar-highlight-content') {
        return 'highlight'

        // add_charts
    } else if (event.properties['el_text'] === 'Add more charts') {
        return 'add_charts'

        // add_alarms
    } else if (event.properties['el_text'] === 'Add more alarms') {
        return 'add_alarms'
    } else {
        return 'other'
    }
}

function getInteractionDetailAgent(event) {
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
        if (event.properties.hasOwnProperty('el_id') && event.properties.hasOwnProperty('el_text')) {
            return event.properties['el_data_netdata'].concat('.', event.properties['el_text'])
        } else if (event.properties.hasOwnProperty('el_id') && event.properties.hasOwnProperty('el_title')) {
            return event.properties['el_data_netdata'].concat('.', event.properties['el_title'])
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
                return event.properties['el_data_testid_1'].concat(' ', event.properties['el_data_testid_3'])
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
        if (event.properties.hasOwnProperty('el_href') && event.properties['el_href'].includes('#alarm_all_')) {
            return event.properties['el_text']
        } else if (event.properties.hasOwnProperty('el_class_page_number')) {
            return 'page_number'
        } else if (event.properties['el_id'] === 'root') {
            return 'open'
        } else if (event.properties['el_text'] === 'Active' || event.properties['el_id'] === 'alarms_active') {
            return 'active'
        } else if (event.properties['el_text'] === 'Log') {
            return 'log'
        } else if (event.properties['el_text'] === 'All') {
            return 'all'
        } else if (event.properties.hasOwnProperty('el_class_warning') && event.properties.hasOwnProperty('el_text')) {
            if (event.properties['el_text'].includes(':') || event.properties['el_text'].includes('%')) {
                return 'warn'
            } else {
                return 'warn__'.concat(event.properties['el_text'])
            }
        } else if (event.properties.hasOwnProperty('el_class_success') && event.properties.hasOwnProperty('el_text')) {
            if (event.properties['el_text'].includes(':') || event.properties['el_text'].includes('%')) {
                return 'norm'
            } else {
                return 'norm__'.concat(event.properties['el_text'])
            }
        } else if (event.properties.hasOwnProperty('el_class_danger') && event.properties.hasOwnProperty('el_text')) {
            if (event.properties['el_text'].includes(':') || event.properties['el_text'].includes('%')) {
                return 'crit'
            } else {
                return 'crit__'.concat(event.properties['el_text'])
            }
        } else if (event.properties.hasOwnProperty('el_class_info') && event.properties.hasOwnProperty('el_text')) {
            if (event.properties['el_text'].includes(':') || event.properties['el_text'].includes('%')) {
                return 'undef'
            } else {
                return 'undef__'.concat(event.properties['el_text'])
            }
        } else if (event.properties['el_text'] === 'Close' || event.properties['el_text'] === '×') {
            return 'close'
        } else if (event.properties['el_title'] === 'Refresh' && event.properties['el_id'] === 'alarms_log') {
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

function processPropertiesAgent(event) {
    event = splitPathName(event)

    // has_alarms_critical
    if (typeof event.properties['alarms_critical'] === 'number') {
        event.properties['has_alarms_critical'] = event.properties['alarms_critical'] > 0
    }

    // has_alarms_warning
    if (typeof event.properties['alarms_warning'] === 'number') {
        event.properties['has_alarms_warning'] = event.properties['alarms_warning'] > 0
    }

    // add attribute for each build info flag
    if (event.properties['netdata_buildinfo']) {
        ;[...new Set(event.properties['netdata_buildinfo'].split('|'))].forEach((buildInfo) => {
            if (buildInfo !== '' && buildInfo !== null) {
                event.properties[`netdata_buildinfo_${cleanPropertyName(buildInfo)}`] = true
            }
        })
    }

    // add attribute for each host collector
    if (event.properties['host_collectors']) {
        // only process if not empty
        if (event.properties['host_collectors'][0] != null) {
            // make set for both plugins and modules present
            let plugins = [...new Set(event.properties['host_collectors'].map((a) => a.plugin))]
            let modules = [...new Set(event.properties['host_collectors'].map((a) => a.module))]

            // add flag for each plugin
            plugins.forEach((plugin) => {
                if (plugin !== '' && plugin !== null) {
                    event.properties[`host_collector_plugin_${cleanPropertyName(plugin)}`] = true
                }
            })

            // add flag for each module
            modules.forEach((module) => {
                if (module !== '' && module !== null) {
                    event.properties[`host_collector_module_${cleanPropertyName(module)}`] = true
                }
            })
        }
    }

    // check if netdata_machine_guid property exists
    if (typeof event.properties['netdata_machine_guid'] === 'string') {
        // flag if empty string
        if (event.properties['netdata_machine_guid'] === '') {
            event.properties['netdata_machine_guid'] = 'empty'
            event.properties['netdata_machine_guid_is_empty'] = true
        } else {
            event.properties['netdata_machine_guid_is_empty'] = false
        }
    }

    // check if netdata_machine_guid property exists
    if (typeof event.properties['netdata_person_id'] === 'string') {
        // flag if empty string
        if (event.properties['netdata_person_id'] === '') {
            event.properties['netdata_person_id'] = 'empty'
            event.properties['netdata_person_id_is_empty'] = true
        } else {
            event.properties['netdata_person_id_is_empty'] = false
        }
    }

    // check if $distinct_id property exists
    if (typeof event.properties['distinct_id'] === 'string') {
        // flag if empty string
        if (event.properties['distinct_id'] === '') {
            event.properties['distinct_id'] = 'empty'
            event.properties['distinct_id_is_empty'] = true
        } else {
            event.properties['distinct_id_is_empty'] = false
        }
    }

    // interaction_type
    event.properties['interaction_type'] = getInteractionTypeAgent(event)
    event.properties['interaction_detail'] = getInteractionDetailAgent(event)
    event.properties['interaction_token'] = event.properties['interaction_type'].concat(
        '|',
        event.properties['interaction_detail']
    )
    //if (event.event === '$autocapture' && event.properties.hasOwnProperty('interaction_token')) {
    //    event.event = event.properties['interaction_token']
    //}

    return event
}

function processElementsAgentInstaller(event) {
    // placeholder for now

    return event
}

function processPropertiesAgentInstaller(event) {
    // only process if install_options not empty
    if (event.properties['install_options'] != null) {
        // make set for install options
        let installOptions = [...new Set((event.properties['install_options'] + ' ').split('--'))]

        // make flag for each option
        installOptions.forEach((installOption) => {
            if (installOption !== '' && installOption !== null) {
                let installOptionKV = installOption.split(' ')
                event.properties[`opt_${cleanPropertyName(installOptionKV[0])}`] = installOptionKV[1]
            }
        })
    }

    return event
}

function processElementsCloud(event) {
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
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                        // give nice names in posthog
                        event.properties['event_category'] = arr[0]
                        event.properties['event_action'] = arr[1]
                        event.properties['event_label'] = arr[2]
                        event.properties['event_value'] = arr[3]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_data_menuid
                if ('attr__data-menuid' in element && element['attr__data-menuid'] !== null) {
                    event.properties['el_data_menuid'] = element['attr__data-menuid']
                }

                // el_data_submenuid
                if ('attr__data-submenuid' in element && element['attr__data-submenuid'] !== null) {
                    event.properties['el_data_submenuid'] = element['attr__data-submenuid']
                }

                // el_data_chartid
                if ('attr__data-chartid' in element && element['attr__data-chartid'] !== null) {
                    event.properties['el_data_chartid'] = element['attr__data-chartid']
                }

                // el_id_menu
                if (
                    'attr__id' in element &&
                    element['attr__id'] !== null &&
                    element['attr__id'].substring(0, 5) === 'menu_'
                ) {
                    event.properties['el_id_menu'] = element['attr__id']
                    event.properties['el_menu'] = element['attr__id'].split('_submenu')[0].replace('menu_', '')
                    if (element['attr__id'].includes('_submenu_')) {
                        event.properties['el_submenu'] = element['attr__id'].split('_submenu_')[1]
                    } else {
                        event.properties['el_submenu'] = ''
                    }
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }
            })
    }

    return event
}

function processPropertiesCloud(event) {
    event = splitPathName(event)

    return event
}

function processElementsStaging(event) {
    // extract properties from elements
    if (event.properties['$elements']) {
        // process each element, reverse to use posthog order as preference
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                // el_data_track
                if ('attr__data-track' in element) {
                    event.properties['el_data_track'] = element['attr__data-track']

                    // el_data_track_0
                    if (element['attr__data-track'].includes('::')) {
                        arr = element['attr__data-track'].split('::')
                        event.properties['el_data_track_0'] = arr[0]
                        event.properties['el_data_track_1'] = arr[1]
                        event.properties['el_data_track_2'] = arr[2]
                        event.properties['el_data_track_3'] = arr[3]
                        event.properties['el_data_track_4'] = arr[4]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_data_menuid
                if ('attr__data-menuid' in element && element['attr__data-menuid'] !== null) {
                    event.properties['el_data_menuid'] = element['attr__data-menuid']
                }

                // el_data_submenuid
                if ('attr__data-submenuid' in element && element['attr__data-submenuid'] !== null) {
                    event.properties['el_data_submenuid'] = element['attr__data-submenuid']
                }

                // el_data_chartid
                if ('attr__data-chartid' in element && element['attr__data-chartid'] !== null) {
                    event.properties['el_data_chartid'] = element['attr__data-chartid']
                }

                // el_id_menu
                if (
                    'attr__id' in element &&
                    element['attr__id'] !== null &&
                    element['attr__id'].substring(0, 5) === 'menu_'
                ) {
                    event.properties['el_id_menu'] = element['attr__id']
                    event.properties['el_menu'] = element['attr__id'].split('_submenu')[0].replace('menu_', '')
                    if (element['attr__id'].includes('_submenu_')) {
                        event.properties['el_submenu'] = element['attr__id'].split('_submenu_')[1]
                    } else {
                        event.properties['el_submenu'] = ''
                    }
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }
            })
    }

    return event
}

function processPropertiesStaging(event) {
    event = splitPathName(event)

    return event
}

function processElementsTesting(event) {
    // extract properties from elements
    if (event.properties['$elements']) {
        // process each element, reverse to use posthog order as preference
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                // el_data_track
                if ('attr__data-track' in element) {
                    event.properties['el_data_track'] = element['attr__data-track']

                    // el_data_track_0
                    if (element['attr__data-track'].includes('::')) {
                        arr = element['attr__data-track'].split('::')
                        event.properties['el_data_track_0'] = arr[0]
                        event.properties['el_data_track_1'] = arr[1]
                        event.properties['el_data_track_2'] = arr[2]
                        event.properties['el_data_track_3'] = arr[3]
                        event.properties['el_data_track_4'] = arr[4]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_data_menuid
                if ('attr__data-menuid' in element && element['attr__data-menuid'] !== null) {
                    event.properties['el_data_menuid'] = element['attr__data-menuid']
                }

                // el_data_submenuid
                if ('attr__data-submenuid' in element && element['attr__data-submenuid'] !== null) {
                    event.properties['el_data_submenuid'] = element['attr__data-submenuid']
                }

                // el_data_chartid
                if ('attr__data-chartid' in element && element['attr__data-chartid'] !== null) {
                    event.properties['el_data_chartid'] = element['attr__data-chartid']
                }

                // el_id_menu
                if (
                    'attr__id' in element &&
                    element['attr__id'] !== null &&
                    element['attr__id'].substring(0, 5) === 'menu_'
                ) {
                    event.properties['el_id_menu'] = element['attr__id']
                    event.properties['el_menu'] = element['attr__id'].split('_submenu')[0].replace('menu_', '')
                    if (element['attr__id'].includes('_submenu_')) {
                        event.properties['el_submenu'] = element['attr__id'].split('_submenu_')[1]
                    } else {
                        event.properties['el_submenu'] = ''
                    }
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }
            })
    }

    return event
}

function processPropertiesTesting(event) {
    event = splitPathName(event)

    return event
}

function processElementsWebsite(event) {
    // extract properties from elements
    if (event.properties['$elements']) {
        // process each element, reverse to use posthog order as preference
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                // el_data_track
                if ('attr__data-track' in element) {
                    event.properties['el_data_track'] = element['attr__data-track']

                    // el_data_track_0
                    if (element['attr__data-track'].includes('::')) {
                        arr = element['attr__data-track'].split('::')
                        event.properties['el_data_track_0'] = arr[0]
                        event.properties['el_data_track_1'] = arr[1]
                        event.properties['el_data_track_2'] = arr[2]
                        event.properties['el_data_track_3'] = arr[3]
                        event.properties['el_data_track_4'] = arr[4]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }
            })
    }

    return event
}

function processPropertiesWebsite(event) {
    event = splitPathName(event)

    return event
}

function processElementsLearn(event) {
    // extract properties from elements
    if (event.properties['$elements']) {
        // process each element, reverse to use posthog order as preference
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                // el_data_track
                if ('attr__data-track' in element) {
                    event.properties['el_data_track'] = element['attr__data-track']

                    // el_data_track_0
                    if (element['attr__data-track'].includes('::')) {
                        arr = element['attr__data-track'].split('::')
                        event.properties['el_data_track_0'] = arr[0]
                        event.properties['el_data_track_1'] = arr[1]
                        event.properties['el_data_track_2'] = arr[2]
                        event.properties['el_data_track_3'] = arr[3]
                        event.properties['el_data_track_4'] = arr[4]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }

                // el_aria_label
                if (
                    'attributes' in element &&
                    element['attributes'] !== null &&
                    'attr__aria-label' in element['attributes']
                ) {
                    event.properties['el_aria_label'] = element['attributes']['attr__aria-label']
                }
            })
    }

    return event
}

function processPropertiesLearn(event) {
    event = splitPathName(event)

    return event
}

function processElementsCommunity(event) {
    // extract properties from elements
    if (event.properties['$elements']) {
        // process each element, reverse to use posthog order as preference
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                // el_data_track
                if ('attr__data-track' in element) {
                    event.properties['el_data_track'] = element['attr__data-track']

                    // el_data_track_0
                    if (element['attr__data-track'].includes('::')) {
                        arr = element['attr__data-track'].split('::')
                        event.properties['el_data_track_0'] = arr[0]
                        event.properties['el_data_track_1'] = arr[1]
                        event.properties['el_data_track_2'] = arr[2]
                        event.properties['el_data_track_3'] = arr[3]
                        event.properties['el_data_track_4'] = arr[4]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }
            })
    }

    return event
}

function processPropertiesCommunity(event) {
    event = splitPathName(event)

    return event
}

function processElementsBlog(event) {
    // extract properties from elements
    if (event.properties['$elements']) {
        // process each element, reverse to use posthog order as preference
        event.properties['$elements']
            .slice()
            .reverse()
            .forEach((element) => {
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

                // el_data_track
                if ('attr__data-track' in element) {
                    event.properties['el_data_track'] = element['attr__data-track']

                    // el_data_track_0
                    if (element['attr__data-track'].includes('::')) {
                        arr = element['attr__data-track'].split('::')
                        event.properties['el_data_track_0'] = arr[0]
                        event.properties['el_data_track_1'] = arr[1]
                        event.properties['el_data_track_2'] = arr[2]
                        event.properties['el_data_track_3'] = arr[3]
                        event.properties['el_data_track_4'] = arr[4]
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
                } else if ('text' in element && element['text'] !== null && element['text'] !== '') {
                    event.properties['el_text'] = element['text']
                }

                // el_class
                if ('attr__class' in element && element['attr__class'] !== null) {
                    event.properties['el_class'] = element['attr__class']
                }

                // el_aria_label
                if (
                    'attributes' in element &&
                    element['attributes'] !== null &&
                    'attr__aria-label' in element['attributes']
                ) {
                    event.properties['el_aria_label'] = element['attributes']['attr__aria-label']
                }
            })
    }

    return event
}

function processPropertiesBlog(event) {
    event = splitPathName(event)

    return event
}

//import URL from 'url';

const netdataPluginVersion = '0.0.15'

function processEvent(event) {
    if (event.properties) {
        event.properties['event_ph'] = event.event
        event.properties['netdata_posthog_plugin_version'] = netdataPluginVersion

        // determine processing based on url
        if ('$current_url' in event.properties) {
            // try extract specific url params
            //if (event.properties['$current_url'].startsWith('http')) {
            //    const urlParams = new URL(event.properties['$current_url']).searchParams
            //    if (event.properties['$current_url'].includes('utm_source')) event.properties['url_param_utm_source'] = urlParams.get('utm_source');
            //}

            if (
                ['agent dashboard', 'agent backend'].includes(event.properties['$current_url']) ||
                isDemo(event.properties['$current_url']) ||
                event.properties['$current_url'].startsWith('https://netdata.corp.app.netdata.cloud')
            ) {
                event.properties['event_source'] = 'agent'
                event = processElementsAgent(event)
                event = processPropertiesAgent(event)
            } else if (['agent installer'].includes(event.properties['$current_url'])) {
                event.properties['event_source'] = 'agent installer'
                event = processElementsAgentInstaller(event)
                event = processPropertiesAgentInstaller(event)
            } else if (event.properties['$current_url'].startsWith('https://www.netdata.cloud')) {
                event.properties['event_source'] = 'website'
                event = processElementsWebsite(event)
                event = processPropertiesWebsite(event)
            } else if (event.properties['$current_url'].includes('netdata-website.netlify.app')) {
                event.properties['event_source'] = 'website_preview'
                event = processElementsWebsite(event)
                event = processPropertiesWebsite(event)
            } else if (event.properties['$current_url'].startsWith('https://learn.netdata.cloud')) {
                event.properties['event_source'] = 'learn'
                event = processElementsLearn(event)
                event = processPropertiesLearn(event)
            } else if (event.properties['$current_url'].includes('netdata-docusaurus.netlify.app')) {
                event.properties['event_source'] = 'learn_preview'
                event = processElementsLearn(event)
                event = processPropertiesLearn(event)
            } else if (event.properties['$current_url'].startsWith('https://blog.netdata.cloud')) {
                event.properties['event_source'] = 'blog'
                event = processElementsBlog(event)
                event = processPropertiesBlog(event)
            } else if (event.properties['$current_url'].includes('netdata-blog.netlify.app')) {
                event.properties['event_source'] = 'blog_preview'
                event = processElementsBlog(event)
                event = processPropertiesBlog(event)
            } else if (event.properties['$current_url'].startsWith('https://community.netdata.cloud')) {
                event.properties['event_source'] = 'community'
                event = processElementsCommunity(event)
                event = processPropertiesCommunity(event)
            } else if (event.properties['$current_url'].startsWith('https://staging.netdata.cloud')) {
                event.properties['event_source'] = 'staging'
                event = processElementsStaging(event)
                event = processPropertiesStaging(event)
            } else if (event.properties['$current_url'].startsWith('https://testing.netdata.cloud')) {
                event.properties['event_source'] = 'testing'
                event = processElementsTesting(event)
                event = processPropertiesTesting(event)
            } else if (
                event.properties['$current_url'].startsWith('https://app.netdata.cloud') ||
                event.properties['$current_url'].includes(':19999/spaces/') ||
                event.properties['$current_url'].includes('/spaces/')
            ) {
                if (event.properties['$current_url'].startsWith('https://app.netdata.cloud')) {
                    event.properties['event_source'] = 'cloud'
                } else {
                    event.properties['event_source'] = 'cloud_agent'
                }

                event = processElementsCloud(event)
                event = processPropertiesCloud(event)
            } else {
                event.properties['event_source'] = 'unknown'
            }
        } else if (event.properties['event_ph'] === '$identify') {
            event.properties['event_source'] = 'cloud'
            event = processElementsCloud(event)
            event = processPropertiesCloud(event)
        } else {
            event.properties['event_source'] = 'unknown'
        }
    }

    return event
}

module.exports = {
    processEvent,
}
