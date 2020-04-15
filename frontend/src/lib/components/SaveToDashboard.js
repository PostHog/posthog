import React, { Component } from 'react'
import { Modal } from './Modal'
import { toast } from 'react-toastify'
import { Link } from 'react-router-dom'
import { Button } from 'antd'

export class SaveToDashboard extends Component {
    constructor(props) {
        super(props)

        this.state = {}
        this.Modal = this.Modal.bind(this)
    }
    Toast({ closeToast }) {
        return (
            <div>
                Panel added to dashboard.
                <Link to="/">Click here to see it.</Link>
            </div>
        )
    }
    onSubmit = () => {
        event.preventDefault()
        this.props.onSubmit(event.target.name.value, () => {
            toast(this.Toast)
            this.setState({ openModal: false })
        })
    }

    Modal() {
        return (
            <Modal title="Add graph to dashboard" onDismiss={() => this.setState({ openModal: false })}>
                <form onSubmit={this.onSubmit}>
                    <label>Panel name on dashboard</label>
                    <input
                        name="name"
                        autoFocus
                        required
                        type="text"
                        className="form-control"
                        placeholder="Users who did x"
                        defaultValue={this.props.name}
                    />
                    <br />
                    <button type="submit" className="btn btn-success">
                        Add panel to dashboard
                    </button>
                </form>
            </Modal>
        )
    }
    render() {
        return (
            <span className="save-to-dashboard">
                {this.state.openModal && <this.Modal />}
                <Button onClick={() => this.setState({ openModal: true })} type="primary">
                    Add to dashboard
                </Button>
            </span>
        )
    }
}
