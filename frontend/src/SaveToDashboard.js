import React, { Component } from 'react'
import api from './Api';
import Modal from './Modal';
import { toast } from 'react-toastify';
import { Link } from 'react-router-dom';

export default class SaveToDashboard extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.Modal = this.Modal.bind(this)
        this.save = this.save.bind(this)
    }
    Toast({closeToast}) {
        return <div>
            Panel added to dashboard.
            <Link to='/'>Click here to see it.</Link>
        </div>
    }
    save(event) {
        event.preventDefault();
        api.create('api/dashboard', {
            filters: this.props.filters,
            type: this.props.type,
            name: event.target.name.value
        }).then(() => {
            toast(this.Toast)
            this.setState({openModal: false})
        })
    }
    Modal() {
        return <Modal title='Add graph to dashboard' onDismiss={() => this.setState({openModal: false})}>
            <form onSubmit={this.save}>
                <label>Panel name on dashboard</label>
                <input name="name" autoFocus required type="text" className='form-control' placeholder="Users who did x" defaultValue={this.props.name} /><br />
                <button type="submit" className='btn btn-success'>Add panel to dashboard</button>
            </form>
        </Modal>

    }
    render() {
        return <span className='save-to-dashboard'>
            {this.state.openModal && <this.Modal />}
            <button onClick={() => this.setState({openModal: true})} className={'btn btn-secondary btn-sm ' + this.props.className}>Add to dashboard</button>
        </span>
    }
}