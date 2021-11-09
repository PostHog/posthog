import React, { useState } from 'react'
import { Col, Row } from 'antd'
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
    const [repositorySectionsOpen, setRepositorySectionsOpen] = useState([RepositorySection.Official])

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
            <Subtitle subtitle="Plugin Repository" />
            <PluginsSearch />
            <div>
                {(!repositoryLoading || filteredUninstalledPlugins.length > 0) && (
                    <>
                        <Row gutter={16} style={{ marginTop: 16, display: 'block' }}>
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
                                            {` Official Plugins (${officialPlugins.length})`}
                                        </>
                                    }
                                />
                            </div>
                            {repositorySectionsOpen.includes(RepositorySection.Official) && (
                                <>
                                    <Col span={24}>
                                        {officialPlugins.length > 0
                                            ? 'Official plugins are built and maintained by the PostHog team.'
                                            : 'You have already installed all official plugins!'}
                                    </Col>
                                    <br />
                                    {officialPlugins.map((plugin) => {
                                        return (
                                            <PluginCard
                                                key={plugin.url}
                                                plugin={{
                                                    name: plugin.name,
                                                    url: plugin.url,
                                                    description: plugin.description,
                                                }}
                                                maintainer={plugin.maintainer}
                                            />
                                        )
                                    })}
                                </>
                            )}
                        </Row>
                        <Row gutter={16} style={{ marginTop: 16, display: 'block' }}>
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
                                            {` Community Plugins (${communityPlugins.length})`}
                                        </>
                                    }
                                />
                            </div>
                            {repositorySectionsOpen.includes(RepositorySection.Community) && (
                                <>
                                    <Col span={24}>
                                        {communityPlugins.length > 0 ? (
                                            <span>
                                                Community plugins are not built nor maintained by the PostHog team.{' '}
                                                <a
                                                    href="https://posthog.com/docs/plugins/build"
                                                    target="_blank"
                                                    rel="noopener"
                                                >
                                                    Anyone, including you, can build a plugin.
                                                </a>
                                            </span>
                                        ) : (
                                            'You have already installed all community plugins!'
                                        )}
                                    </Col>
                                    <br />
                                    {communityPlugins.map((plugin) => {
                                        return (
                                            <PluginCard
                                                key={plugin.url}
                                                plugin={{
                                                    name: plugin.name,
                                                    url: plugin.url,
                                                    description: plugin.description,
                                                }}
                                                maintainer={plugin.maintainer}
                                            />
                                        )
                                    })}
                                </>
                            )}
                        </Row>
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
