import {cleanPropertyName, splitPathName} from "./utils";
import {getInteractionTypeAgent} from "./interaction_type_agent";
import {getInteractionDetailAgent} from "./interaction_detail_agent";

export function processPropertiesAgent(event) {

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
        [...new Set(event.properties['netdata_buildinfo'].split('|'))].forEach((buildInfo) => {
            if ((buildInfo !== "") && (buildInfo !== null)){
                event.properties[`netdata_buildinfo_${cleanPropertyName(buildInfo)}`] = true
            }
        })
    }

    // add attribute for each host collector
    if (event.properties['host_collectors']) {

        // only process if not empty
        if (event.properties['host_collectors'][0] != null) {

            // make set for both plugins and modules present
            let plugins = [...new Set(event.properties['host_collectors'].map(a => a.plugin))];
            let modules = [...new Set(event.properties['host_collectors'].map(a => a.module))];

            // add flag for each plugin
            plugins.forEach((plugin) => {
                if ((plugin !== "") && (plugin !== null)){
                    event.properties[`host_collector_plugin_${cleanPropertyName(plugin)}`] = true
                }
            })

            // add flag for each module
            modules.forEach((module) => {
                if ((module !== "") && (module !== null)){
                    event.properties[`host_collector_module_${cleanPropertyName(module)}`] = true
                }
            })

        }
    }

    // check if netdata_machine_guid property exists
    if (typeof event.properties['netdata_machine_guid'] === 'string') {
        // flag if empty string
        if (event.properties['netdata_machine_guid']==='') {
            event.properties['netdata_machine_guid'] = 'empty'
            event.properties['netdata_machine_guid_is_empty'] = true
        } else {
            event.properties['netdata_machine_guid_is_empty'] = false
        }
    }

    // check if netdata_machine_guid property exists
    if (typeof event.properties['netdata_person_id'] === 'string') {
        // flag if empty string
        if (event.properties['netdata_person_id']==='') {
            event.properties['netdata_person_id'] = 'empty'
            event.properties['netdata_person_id_is_empty'] = true
        } else {
            event.properties['netdata_person_id_is_empty'] = false
        }
    }

    // check if $distinct_id property exists
    if (typeof event.properties['distinct_id'] === 'string') {
        // flag if empty string
        if (event.properties['distinct_id']==='') {
            event.properties['distinct_id'] = 'empty'
            event.properties['distinct_id_is_empty'] = true
        } else {
            event.properties['distinct_id_is_empty'] = false
        }
    }

    // interaction_type
    event.properties['interaction_type'] = getInteractionTypeAgent(event)
    event.properties['interaction_detail'] = getInteractionDetailAgent(event)
    event.properties['interaction_token'] = event.properties['interaction_type'].concat('|',event.properties['interaction_detail'])
    //if (event.event === '$autocapture' && event.properties.hasOwnProperty('interaction_token')) {
    //    event.event = event.properties['interaction_token']
    //}

    return event
}