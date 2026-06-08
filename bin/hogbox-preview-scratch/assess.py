"""Assess the running 8/32 seed box via exec (bypasses the SSH-auth issue)."""
import sys

from hog import client  # HOGENV=prod-us

bid = sys.argv[1] if len(sys.argv) > 1 else "box-a7683bc2907b"
c = client()
box = c.get(bid)
print("status:", box.status, flush=True)
script = r"""
echo '=== marker ==='; test -f /var/lib/hog/snapshot-build-ok && echo MARKER_PRESENT || echo MARKER_ABSENT
echo '=== hog .ssh ==='; ls -la /home/hog/.ssh/ 2>/dev/null; echo '--keys--'; cat /home/hog/.ssh/authorized_keys 2>/dev/null | cut -c1-60
echo '=== mem/uptime ==='; free -h | head -2; uptime
echo '=== whats running ==='; ps -eo pid,rss,comm,args 2>/dev/null | grep -iE 'apt|dpkg|docker|flox|hogli|pnpm|devbox-setup|hog-bootstrap' | grep -v grep | head -12
echo '=== docker ps ==='; docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | head -15 || echo docker-not-up
echo '=== setup log tail ==='; tail -20 /var/log/devbox-setup.log 2>/dev/null || echo no-log
echo '=== oom in dmesg ==='; dmesg 2>/dev/null | grep -iE 'out of memory|killed process|oom-kill' | tail -5 || echo none
"""
r = box.exec(["sh", "-c", script], timeout_seconds=60)
print(f"exit={r.exit_code}\n{r.stdout}", flush=True)
if r.stderr:
    print("STDERR:", r.stderr[-500:], flush=True)
