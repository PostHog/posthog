import React, { useEffect } from 'react'
import { hot } from 'react-hot-loader/root'
import { PluginModal } from 'scenes/plugins/PluginModal'
import { CustomPlugin } from 'scenes/plugins/CustomPlugin'
import { Repository } from 'scenes/plugins/Repository'
import { InstalledPlugins } from 'scenes/plugins/InstalledPlugins'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export const Plugins = hot(_Plugins)
function _Plugins(): JSX.Element {
    const { user } = useValues(userLogic)

    if (!user) {
        return <div />
    }

    if (!user?.plugin_access?.view) {
        useEffect(() => {
            window.location.href = '/'
        }, [])
        return <div />
    }

    return (
        <div>
            <InstalledPlugins />

            {user.plugin_access?.install ? (
                <>
                    <br />
                    <br />
                    <Repository />
                    <br />
                    <br />
                    <CustomPlugin />
                </>
            ) : null}

            <PluginModal />
        </div>
    )
}
