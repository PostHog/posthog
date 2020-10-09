import React from 'react'
import { hot } from 'react-hot-loader/root'
import { PluginModal } from 'scenes/plugins/PluginModal'
import { CustomPlugin } from 'scenes/plugins/CustomPlugin'
import { Repository } from 'scenes/plugins/Repository'
import { InstalledPlugins } from 'scenes/plugins/InstalledPlugins'

export const Plugins = hot(_Plugins)
function _Plugins(): JSX.Element {
    return (
        <div>
            <InstalledPlugins />

            <br />
            <br />

            <Repository />

            <br />
            <br />

            <CustomPlugin />

            <PluginModal />
        </div>
    )
}
