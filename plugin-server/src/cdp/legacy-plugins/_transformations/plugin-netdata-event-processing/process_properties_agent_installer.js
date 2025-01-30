import {cleanPropertyName} from "./utils";

export function processPropertiesAgentInstaller(event) {

    // only process if install_options not empty
    if (event.properties['install_options'] != null) {

        // make set for install options
        let installOptions = [...new Set((event.properties['install_options'] + ' ').split('--'))];

        // make flag for each option
        installOptions.forEach((installOption) => {
            if ((installOption !== "") && (installOption !== null)){
                let installOptionKV = installOption.split(' ')
                event.properties[`opt_${cleanPropertyName(installOptionKV[0])}`] = installOptionKV[1]
            }
        })

    }

    return event
}