export function getInteractionTypeAgent(event) {

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
        (
            event.properties.hasOwnProperty('el_text') || event.properties.hasOwnProperty('el_title')
        ) &&
        event.properties['el_id'].startsWith('chart_')
    ) {

        return 'chart_dim'

    // date_picker
    } else if (
        event.properties['el_id'] === 'date-picker-root' ||
        (
            event.properties.hasOwnProperty('el_data_testid') &&
            event.properties['el_data_testid'].startsWith('date-picker')
        ) ||
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