import React, { Component } from 'react'
import { withRouter } from 'react-router-dom'
import { JSSnippet } from '../lib/utils'

class SendEventsOverlay extends Component {
    constructor(props) {
        super(props)
        this.overlay = React.createRef()
        this.imageRef = React.createRef()
        this.state = { path: this.props.history.location.pathname }
    }
    urlBackgroundMap = {
        '/': 'https://posthog.s3.eu-west-2.amazonaws.com/graphs.png',
        '/actions':
            'https://posthog.s3.eu-west-2.amazonaws.com/preview-actions.png',
        '/trends':
            'https://posthog.s3.eu-west-2.amazonaws.com/preview-action-trends.png',
        '/funnel': 'https://posthog.s3.eu-west-2.amazonaws.com/funnel.png',
        '/paths': 'https://posthog.s3.eu-west-2.amazonaws.com/paths.png',
    }
    componentDidMount() {
        setTimeout(() => this.setState({ animate: true }), 1000)
    }
    componentDidUpdate(prevProps) {
        if (this.state.path != this.props.history.location.pathname) {
            this.setState({
                animate: false,
                path: this.props.history.location.pathname,
            })
        }
    }
    render() {
        let path = this.props.history.location.pathname
        let image = this.urlBackgroundMap[path]
        let { animate } = this.state
        return !this.props.user.has_events && image ? (
            <div
                ref={this.overlay}
                className={
                    'send-events-overlay ' + (this.state.animate && 'animate')
                }
            >
                <img
                    ref={this.imageRef}
                    src={image}
                    style={{ opacity: animate ? 1 : 0 }}
                    className="overlay-image"
                    onLoad={() => this.setState({ animate: true, path })}
                />
                <div className="overlay">
                    <div style={{ width: 400 }} className="overlay-inner">
                        <h2>Start sending events to PostHog</h2>
                        To get started using PostHog, you'll need to send us
                        some events. By copying the snippet below into the
                        header, you can be up and running in minutes! You can
                        put this snippet on any domain, and it'll capture users
                        across.
                        <JSSnippet user={this.props.user} />
                        <a href="https://github.com/PostHog/posthog/wiki/Integrations">
                            Using Python/Ruby/Node/Go/PHP instead?
                        </a>
                        <br />
                        <br />
                        {window.location.href.indexOf('127.0.0.1') > -1 && (
                            <div>
                                <h3>Running locally?</h3>
                                It's hard to send events to PostHog running
                                locally. If you want to have a play,{' '}
                                <a href="/demo" target="_blank">
                                    click here for our 'HogFlix' demo
                                    environment
                                </a>
                                .<br />
                                <br />
                                Once you're ready, you can deploy it to a live
                                environment.
                                <br />
                                <br />
                                <a href="https://heroku.com/deploy?template=https://github.com/posthog/posthog">
                                    <img src="https://www.herokucdn.com/deploy/button.svg" />
                                </a>
                                <br />
                                <br />
                                <a href="https://github.com/PostHog/posthog">
                                    Click here
                                </a>{' '}
                                for instructions on deploying with Docker or
                                from source.
                            </div>
                        )}
                    </div>
                </div>
            </div>
        ) : null
    }
}

export default withRouter(SendEventsOverlay)
