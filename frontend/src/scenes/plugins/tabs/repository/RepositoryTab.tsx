import { useState } from 'react'
import { Row } from 'antd'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import { Subtitle } from 'lib/components/PageHeader'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { PluginsSearch } from '../../PluginsSearch'
import { CaretRightOutlined, CaretDownOutlined } from '@ant-design/icons'

export enum RepositorySection {
    Official = 'official',
    Community = 'community',
}

export function RepositoryTab(): JSX.Element {
    const { repositoryLoading, filteredUninstalledPlugins } = useValues(pluginsLogic)
    const [repositorySectionsOpen, setRepositorySectionsOpen] = useState([
        RepositorySection.Official,
        RepositorySection.Community,
    ])

    const officialPlugins = filteredUninstalledPlugins.filter((plugin) => plugin.maintainer === 'official')
    const communityPlugins = filteredUninstalledPlugins.filter((plugin) => plugin.maintainer === 'community')

    const toggleRepositorySectionOpen = (section: RepositorySection): void => {
        if (repositorySectionsOpen.includes(section)) {
            setRepositorySectionsOpen(repositorySectionsOpen.filter((s) => section !== s))
            return
        }
        setRepositorySectionsOpen([...repositorySectionsOpen, section])
    }

    return (
        <div>
            <Subtitle subtitle="App Repository" />
            <PluginsSearch />
            <div>
                {(!repositoryLoading || filteredUninstalledPlugins.length > 0) && (
                    <>
                        <div className="-mx-2">
                            <div
                                className="plugins-repository-tab-section-header"
                                onClick={() => toggleRepositorySectionOpen(RepositorySection.Official)}
                            >
                                <Subtitle
                                    subtitle={
                                        <>
                                            {repositorySectionsOpen.includes(RepositorySection.Official) ? (
                                                <CaretDownOutlined />
                                            ) : (
                                                <CaretRightOutlined />
                                            )}
                                            {` Official apps (${officialPlugins.length})`}
                                        </>
                                    }
                                />
                            </div>
                            {repositorySectionsOpen.includes(RepositorySection.Official) && (
                                <>
                                    <div className="px-2">
                                        {officialPlugins.length > 0
                                            ? 'Official apps are built and maintained by the PostHog team.'
                                            : 'You have already installed all official apps!'}
                                    </div>
                                    <br />
                                    {officialPlugins.map((plugin) => {
                                        return (
                                            <PluginCard
                                                key={plugin.url}
                                                plugin={{
                                                    name: plugin.name,
                                                    url: plugin.url,
                                                    icon: plugin.icon,
                                                    description: plugin.description,
                                                }}
                                                maintainer={plugin.maintainer}
                                            />
                                        )
                                    })}
                                </>
                            )}
                        </div>
                        <div className="-mx-2">
                            <div
                                className="plugins-repository-tab-section-header"
                                onClick={() => toggleRepositorySectionOpen(RepositorySection.Community)}
                            >
                                <Subtitle
                                    subtitle={
                                        <>
                                            {repositorySectionsOpen.includes(RepositorySection.Community) ? (
                                                <CaretDownOutlined />
                                            ) : (
                                                <CaretRightOutlined />
                                            )}
                                            {` Community apps (${communityPlugins.length})`}
                                        </>
                                    }
                                />
                            </div>
                            {repositorySectionsOpen.includes(RepositorySection.Community) && (
                                <>
                                    <div className="px-2">
                                        {communityPlugins.length > 0 ? (
                                            <span>
                                                Community apps are not built nor maintained by the PostHog team.{' '}
                                                <a
                                                    href="https://posthog.com/docs/apps/build"
                                                    target="_blank"
                                                    rel="noopener"
                                                >
                                                    Anyone, including you, can build an app.
                                                </a>
                                            </span>
                                        ) : (
                                            'You have already installed all community apps!'
                                        )}
                                    </div>
                                    <br />
                                    {communityPlugins.map((plugin) => {
                                        return (
                                            <PluginCard
                                                key={plugin.url}
                                                plugin={{
                                                    name: plugin.name,
                                                    url: plugin.url,
                                                    icon: plugin.icon,
                                                    description: plugin.description,
                                                }}
                                                maintainer={plugin.maintainer}
                                            />
                                        )
                                    })}
                                </>
                            )}
                        </div>
                    </>
                )}
            </div>
            {repositoryLoading && filteredUninstalledPlugins.length === 0 && (
                <Row gutter={16}>
                    <PluginLoading />
                </Row>
            )}
        </div>
    )
}
