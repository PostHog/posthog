import React, { Component } from 'react'
import { Card, uuid } from '../../lib/utils'
import api from '../../lib/api'
import Select from 'react-select'
import { toast } from 'react-toastify'
import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'

export class EditFunnel extends Component {
    constructor(props) {
        super(props);

        this.state = {
            actions: false,
            steps: (props.funnel &&
                (props.funnel.steps.length > 0
                    ? props.funnel.steps
                    : [{ id: uuid(), order: 0 }])) || [{ id: uuid(), order: 0 }],
            name: props.funnel && props.funnel.name,
            id: (props.funnel && props.funnel.id) || props.match.params.id
        };
        this.Step = this.Step.bind(this);
        this.onSubmit = this.onSubmit.bind(this);
        this.fetchActions.call(this);
        if (this.state.id) this.fetchFunnel.call(this);

        import("react-beautiful-dnd").then(dnd => {
            this.dnd = dnd;
            this.setState({ dndLoaded: true });
        });
    }
    fetchFunnel() {
        api.get("api/funnel/" + this.state.id).then(funnel =>
            this.setState({
                steps:
                    funnel.steps.length > 0 ? funnel.steps : [{ id: uuid(), order: 0 }],
                name: funnel.name
            })
        );
    }
    fetchActions() {
        api
            .get("api/action")
            .then(actions => this.setState({ actions: actions.results }));
    }
    Step(step) {
        let { steps, actions } = this.state;
        let selectedAction =
            actions && actions.filter(action => action.id == step.action_id)[0];
        return (
            <this.dnd.Draggable draggableId={step.id.toString()} index={step.order}>
                {draggableProvider => (
                    <div
                        ref={draggableProvider.innerRef}
                        className="flex-grow-1 p-3"
                        {...draggableProvider.draggableProps}
                        {...draggableProvider.dragHandleProps}
                    >
                        <Card
                            className="card-funnel"
                            style={{ margin: 0 }}
                            title={
                                <span>
                  Step {step.index + 1}
                                    <button
                                        type="button"
                                        className="close float-right"
                                        onClick={() =>
                                            this.setState(
                                                { steps: steps.filter(s => s.id != step.id) },
                                                this.onSubmit
                                            )
                                        }
                                    >
                    <span style={{ display: "block" }}>×</span>
                  </button>
                </span>
                            }
                        >
                            <div className="card-body">
                                <Select
                                    required
                                    onChange={item => {
                                        this.setState(
                                            {
                                                steps: this.state.steps.map(s =>
                                                    s.id == step.id
                                                        ? { ...step, action_id: item.value }
                                                        : s
                                                )
                                            },
                                            this.onSubmit
                                        );
                                    }}
                                    defaultOptions
                                    options={
                                        actions &&
                                        actions.map(action => ({
                                            label: action.name,
                                            value: action.id
                                        }))
                                    }
                                    value={{
                                        label: selectedAction && selectedAction.name,
                                        value: step.action_id
                                    }}
                                />
                                {step.action_id && (
                                    <a target="_blank" href={"/action/" + step.action_id}>
                                        Edit action
                                    </a>
                                )}
                            </div>
                        </Card>
                    </div>
                )}
            </this.dnd.Draggable>
        );
    }
    onSubmit(event) {
        if (event) event.preventDefault();
        let save = funnel => {
            toast("Funnel saved.", { autoClose: 3000, hideProgressBar: true });
            this.props.onChange && this.props.onChange(funnel);
        };
        let data = {
            name: this.state.name,
            id: this.state.id,
            steps: this.state.steps
        };
        if (this.state.id) {
            return api.update("api/funnel/" + this.state.id, data).then(save);
        }
        api
            .create("api/funnel", data)
            .then(funnel => this.props.history.push("/funnel/" + funnel.id));
    }
    render() {
        let { dndLoaded, name, steps, actions } = this.state;
        return (
            <form onSubmit={this.onSubmit}>
                <label>Name</label>
                <input
                    required
                    placeholder="User drop off through signup"
                    type="text"
                    autoFocus
                    onChange={e => this.setState({ name: e.target.value })}
                    value={name}
                    onBlur={() => this.onSubmit()}
                    className="form-control"
                />
                {actions && actions.length == 0 && (
                    <div className="alert alert-warning" style={{ marginTop: "1rem" }}>
                        You don't have any actions set up.{" "}
                        <Link to="/actions">Click here to set up an action</Link>
                    </div>
                )}
                <br />
                <br />
                <div className="row">
                    <div className="col-10">
                        {dndLoaded && (
                            <this.dnd.DragDropContext
                                onDragEnd={result => {
                                    if (
                                        !result.destination ||
                                        result.destination.index == result.source.index
                                    )
                                        return;
                                    steps.splice(
                                        result.destination.index,
                                        0,
                                        steps.splice(result.source.index, 1)[0]
                                    );
                                    this.setState({ steps }, this.onSubmit);
                                }}
                            >
                                <this.dnd.Droppable droppableId="1" direction="horizontal">
                                    {(provider, snapshot) => (
                                        <div
                                            ref={provider.innerRef}
                                            className="d-flex flow-row flex-wrap overflow-x-auto"
                                            style={{ margin: "0 -1rem" }}
                                            {...provider.droppableProps}
                                        >
                                            {this.state.steps.map((step, index) => (
                                                <this.Step key={step.id} index={index} {...step} />
                                            ))}
                                            {provider.placeholder}
                                        </div>
                                    )}
                                </this.dnd.Droppable>
                            </this.dnd.DragDropContext>
                        )}
                    </div>
                    <div className="col-2 p-3">
                        <div
                            style={{ height: "100%" }}
                            className="card cursor-pointer d-flex align-content-center"
                            onClick={() =>
                                this.setState({
                                    steps: [...steps, { id: uuid(), order: steps.length }]
                                })
                            }
                        >
              <span
                  style={{ fontSize: 75, textAlign: "center", lineHeight: 1 }}
                  className="text-success "
              >
                +
              </span>
                        </div>
                    </div>
                </div>
                <br />
                <br />
                {this.state.saved && (
                    <p className="text-success">
                        Funnel saved.{" "}
                        <Link to={"/funnel/" + this.state.id}>
                            Click here to go back to the funnel.
                        </Link>
                    </p>
                )}
            </form>
        );
    }
}

EditFunnel.propTypes = {
    history: PropTypes.object,
    funnel: PropTypes.object
};
