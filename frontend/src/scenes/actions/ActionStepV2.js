import React, { Component } from 'react'
import { EventName } from './EventName'
import { AppEditorLink } from 'lib/components/AppEditorLink/AppEditorLink'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import PropTypes from 'prop-types'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'
import { Col } from 'antd'

let getSafeText = (el) => {
    if (!el.childNodes || !el.childNodes.length) return
    let elText = ''
    el.childNodes.forEach((child) => {
        if (child.nodeType !== 3 || !child.textContent) return
        elText += child.textContent
            .trim()
            .replace(/[\r\n]/g, ' ')
            .replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

export class ActionStep extends Component {
    constructor(props) {
        super(props)
        this.state = {
            step: props.step,
            selection: Object.keys(props.step).filter((key) => key !== 'id' && key !== 'isNew' && props.step[key]),
            inspecting: false,
        }
        this.AutocaptureFields = this.AutocaptureFields.bind(this)

        this.box = document.createElement('div')
        document.body.appendChild(this.box)
    }
    drawBox(element) {
        let rect = element.getBoundingClientRect()
        this.box.style.display = 'block'
        this.box.style.position = 'absolute'
        this.box.style.top = `${rect.top + window.pageYOffset}px`
        this.box.style.left = `${rect.left + window.pageXOffset}px`
        this.box.style.width = `${rect.right - rect.left}px`
        this.box.style.height = `${rect.bottom - rect.top}px`
        this.box.style.background = '#007bff'
        this.box.style.opacity = '0.5'
        this.box.style.zIndex = '9999999999'
    }
    onMouseOver = (event) => {
        let el = event.currentTarget
        this.drawBox(el)
        let query = this.props.simmer(el)
        // Turn tags into lower cases
        query = query.replace(/(^[A-Z]+| [A-Z]+)/g, (d) => d.toLowerCase())
        let tagName = el.tagName.toLowerCase()

        let selection = ['selector']
        if (tagName === 'a') selection = ['href', 'selector']
        else if (tagName === 'button') selection = ['text', 'selector']
        else if (el.getAttribute('name')) selection = ['name', 'selector']
        let step = {
            ...this.props.step,
            event: '$autocapture',
            tag_name: tagName,
            href: el.getAttribute('href') || '',
            name: el.getAttribute('name') || '',
            text: getSafeText(el) || '',
            selector: query || '',
            url: window.location.protocol + '//' + window.location.host + window.location.pathname,
        }
        this.setState(
            {
                element: el,
                selection,
            },
            () => this.sendStep(step)
        )
    }
    onKeyDown = (event) => {
        // stop selecting if esc key was pressed
        if (event.keyCode === 27) this.stop()
    }
    start() {
        this.setState({ inspecting: true })
        document.querySelectorAll('a, button, input, select, textarea, label').forEach((element) => {
            element.addEventListener('mouseover', this.onMouseOver, {
                capture: true,
            })
        })
        document.addEventListener('keydown', this.onKeyDown)
        document.body.style.transition = '0.7s box-shadow'
        // document.body.style.boxShadow = 'inset 0 0px 13px -2px #dc3545';
        document.body.style.boxShadow = 'inset 0 0px 30px -5px #007bff'
        this.box.addEventListener('click', this.stop)
    }
    stop = () => {
        this.setState({ inspecting: false })
        this.box.style.display = 'none'
        document.body.style.boxShadow = 'none'
        document.querySelectorAll('a, button, input, select, textarea, label').forEach((element) => {
            element.removeEventListener('mouseover', this.onMouseOver, {
                capture: true,
            })
        })
        document.removeEventListener('keydown', this.onKeyDown)
    }
    sendStep = (step) => {
        step.selection = this.state.selection
        this.props.onChange(step)
    }
    Option = (props) => {
        let onChange = (e) => {
            this.props.step[props.item] = e.target.value

            if (e.target.value && this.state.selection.indexOf(props.item) === -1) {
                this.setState({ selection: this.state.selection.concat([props.item]) }, () =>
                    this.sendStep(this.props.step)
                )
            } else if (!e.target.value && this.state.selection.indexOf(props.item) > -1) {
                this.setState(
                    {
                        selection: this.state.selection.filter((i) => i !== props.item),
                    },
                    () => this.sendStep(this.props.step)
                )
            } else {
                this.sendStep(this.props.step)
            }
        }

        return (
            <div className={'form-group ' + (this.state.selection.indexOf(props.item) > -1 && 'selected')}>
                <label>
                    <input
                        type="checkbox"
                        name="selection"
                        checked={this.state.selection.indexOf(props.item) > -1}
                        value={props.item}
                        onChange={(e) => {
                            let { selection } = this.state
                            if (e.target.checked) {
                                selection.push(props.item)
                            } else {
                                selection = selection.filter((i) => i !== props.item)
                            }
                            this.setState({ selection }, () => this.sendStep(this.props.step))
                        }}
                    />{' '}
                    {props.label} {props.extra_options}
                </label>
                {props.item === 'selector' ? (
                    <textarea className="form-control" onChange={onChange} value={this.props.step[props.item] || ''} />
                ) : (
                    <input
                        data-attr="edit-action-url-input"
                        className="form-control"
                        onChange={onChange}
                        value={this.props.step[props.item] || ''}
                    />
                )}
            </div>
        )
    }
    TypeSwitcher = () => {
        let { step } = this.props
        return (
            <div>
                <div className="type-switcher btn-group">
                    <button
                        type="button"
                        onClick={() =>
                            this.setState(
                                {
                                    selection: Object.keys(step).filter(
                                        (key) => key !== 'id' && key !== 'isNew' && step[key]
                                    ),
                                },
                                () => this.sendStep({ ...step, event: '$autocapture' })
                            )
                        }
                        className={'btn ' + (step.event === '$autocapture' ? 'btn-secondary' : 'btn-light btn-action')}
                    >
                        Autocapture
                    </button>
                    <button
                        type="button"
                        onClick={() => this.setState({ selection: [] }, () => this.sendStep({ ...step, event: '' }))}
                        className={
                            'btn ' +
                            (typeof step.event !== 'undefined' &&
                            step.event !== '$autocapture' &&
                            step.event !== '$pageview'
                                ? 'btn-secondary'
                                : 'btn-light btn-action')
                        }
                    >
                        Custom event
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            this.setState({ selection: ['url'] }, () =>
                                this.sendStep({
                                    ...step,
                                    event: '$pageview',
                                    url: step.url,
                                })
                            )
                        }}
                        className={'btn ' + (step.event === '$pageview' ? 'btn-secondary' : 'btn-light btn-action')}
                        data-attr="action-step-pageview"
                    >
                        Page view
                    </button>
                </div>
            </div>
        )
    }
    AutocaptureFields({ step, actionId }) {
        const AndC = () => {
            return (
                <div className="text-center">
                    <span className="match-condition-badge mc-and">AND</span>
                </div>
            )
        }
        return (
            <div>
                <span>
                    <AppEditorLink actionId={actionId} style={{ margin: '1rem 0' }} className="btn btn-sm btn-light">
                        Select element on site <i className="fi flaticon-export" />
                    </AppEditorLink>
                    <a
                        href="https://posthog.com/docs/features/actions"
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ marginLeft: 8 }}
                    >
                        See documentation.
                    </a>{' '}
                </span>
                <this.Option
                    item="href"
                    label="Link href equals"
                    selector={this.state.element && 'a[href="' + this.state.element.getAttribute('href') + '"]'}
                />
                <AndC />
                <this.Option item="text" label="Text equals" />
                <AndC />
                <this.Option item="selector" label="HTML selector matches" selector={step.selector} />
                <div style={{ marginBottom: 18 }}>
                    <AndC />
                </div>
                <this.Option item="url" extra_options={<this.URLMatching step={step} />} label="URL" />
                {step?.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                    <small style={{ display: 'block', marginTop: -12 }}>{URL_MATCHING_HINTS[step.url_matching]}</small>
                )}
            </div>
        )
    }
    URLMatching = ({ step }) => {
        return (
            <div className="btn-group" style={{ margin: '0 0 0 8px' }}>
                <button
                    onClick={() => this.sendStep({ ...step, url_matching: 'contains' })}
                    type="button"
                    className={
                        'btn btn-sm ' +
                        (!step.url_matching || step.url_matching === 'contains' ? 'btn-secondary' : 'btn-light')
                    }
                >
                    contains
                </button>
                <button
                    onClick={() => this.sendStep({ ...step, url_matching: 'regex' })}
                    type="button"
                    className={'btn btn-sm ' + (step.url_matching === 'regex' ? 'btn-secondary' : 'btn-light')}
                >
                    matches regex
                </button>
                <button
                    onClick={() => this.sendStep({ ...step, url_matching: 'exact' })}
                    type="button"
                    className={'btn btn-sm ' + (step.url_matching === 'exact' ? 'btn-secondary' : 'btn-light')}
                >
                    matches exactly
                </button>
            </div>
        )
    }
    render() {
        let { step, actionId, isOnlyStep, index, identifier, onDelete } = this.props

        return (
            <Col span={24} md={12}>
                <div className="action-step card" style={{ overflow: 'visible' }}>
                    {index > 0 && <div className="match-condition-badge mc-main mc-or">OR</div>}
                    <div className="card-body">
                        {!isOnlyStep && (
                            <div className="remove-wrapper">
                                <button type="button" aria-label="delete" onClick={onDelete}>
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                        )}
                        {<this.TypeSwitcher />}
                        <div
                            style={{
                                marginTop: step.event === '$pageview' ? 20 : 8,
                                paddingBottom: 0,
                            }}
                        >
                            {step.event === '$autocapture' && (
                                <this.AutocaptureFields step={step} actionId={actionId} />
                            )}
                            {step.event != null && step.event !== '$autocapture' && step.event !== '$pageview' && (
                                <div style={{ marginTop: '2rem' }}>
                                    <label>Event name: {step.event}</label>
                                    <EventName
                                        value={step.event}
                                        isActionStep={true}
                                        onChange={(value) =>
                                            this.sendStep({
                                                ...step,
                                                event: value,
                                            })
                                        }
                                    />
                                </div>
                            )}
                            {step.event === '$pageview' && (
                                <div>
                                    <this.Option
                                        item="url"
                                        extra_options={<this.URLMatching step={step} />}
                                        label="URL"
                                    />
                                    {step.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                                        <small style={{ display: 'block', marginTop: -12 }}>
                                            {URL_MATCHING_HINTS[step.url_matching]}
                                        </small>
                                    )}
                                </div>
                            )}

                            {step.event && (
                                <div className="property-filters">
                                    <div className="section-title">Filters</div>
                                    {(!step.properties || step.properties.length === 0) && (
                                        <div className="empty-state">This match group has no additional filters.</div>
                                    )}
                                    <PropertyFilters
                                        propertyFilters={step.properties}
                                        pageKey={identifier}
                                        onChange={(properties) => {
                                            this.sendStep({
                                                ...this.props.step, // Not sure why, but the normal 'step' variable does not work here
                                                properties,
                                            })
                                        }}
                                        showConditionBadges
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </Col>
        )
    }
}
ActionStep.propTypes = {
    step: PropTypes.object,
    simmer: PropTypes.func,
    index: PropTypes.number.isRequired,
}
