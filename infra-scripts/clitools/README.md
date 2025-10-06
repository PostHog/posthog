# Toolbox CLI

The primary function is to help manage and connect to PostHog toolbox pods in a Kubernetes environment.

## Installation

1. Ensure you have Python 3.x installed on your system
2. Clone this repository or download `toolbox.py`
3. Make the script executable (Unix-based systems):

    ```bash
    chmod +x toolbox.py
    ```

## Requirements

- Python 3.x
- kubectl installed and configured
- your current settings and k8s context let you access the cluster that you want your toolbox to be claimed in

## Usage

Run the script using Python:

```bash
python toolbox.py [flags]
```

Or directly (Unix-based systems):

```bash
./toolbox.py [flags]
```

### What it Does

The toolbox CLI:

1. Authenticates your AWS identity
2. Finds an available PostHog toolbox pod or connects to one you've already claimed
3. Claims the pod for a specified duration (default 12 hours)
4. Provides an interactive shell session to the pod
5. Offers to delete the pod when you exit the shell

### Available Flags

| Flag                     | Description                                      | Default |
| ------------------------ | ------------------------------------------------ | ------- |
| `--claim-duration HOURS` | Number of hours to claim the pod for             | 12      |
| `--update-claim`         | Update the termination time of your existing pod | False   |

### Examples

1. Connect to a pod with default 12-hour claim:

```bash
python toolbox.py
```

2. Connect to a pod with a custom claim duration:

```bash
python toolbox.py --claim-duration 4
```

3. Extend the duration of your existing pod:

```bash
python toolbox.py --update-claim --claim-duration 24
```

### Notes

- If no pods are available, the script will wait up to 5 minutes for a pod to become available
- When you exit the pod shell, you'll be prompted whether to delete the pod
- If something doesn't work as expected, reach out to #team-infrastructure for assistance
