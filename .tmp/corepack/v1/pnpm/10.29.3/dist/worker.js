"use strict";
var __getOwnPropNames = Object.getOwnPropertyNames;
var __commonJS = (cb, mod) => function __require() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};

// ../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/polyfills.js
var require_polyfills = __commonJS({
  "../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/polyfills.js"(exports2, module2) {
    var constants = require("constants");
    var origCwd = process.cwd;
    var cwd = null;
    var platform = process.env.GRACEFUL_FS_PLATFORM || process.platform;
    process.cwd = function() {
      if (!cwd)
        cwd = origCwd.call(process);
      return cwd;
    };
    try {
      process.cwd();
    } catch (er) {
    }
    if (typeof process.chdir === "function") {
      chdir = process.chdir;
      process.chdir = function(d) {
        cwd = null;
        chdir.call(process, d);
      };
      if (Object.setPrototypeOf) Object.setPrototypeOf(process.chdir, chdir);
    }
    var chdir;
    module2.exports = patch;
    function patch(fs) {
      if (constants.hasOwnProperty("O_SYMLINK") && process.version.match(/^v0\.6\.[0-2]|^v0\.5\./)) {
        patchLchmod(fs);
      }
      if (!fs.lutimes) {
        patchLutimes(fs);
      }
      fs.chown = chownFix(fs.chown);
      fs.fchown = chownFix(fs.fchown);
      fs.lchown = chownFix(fs.lchown);
      fs.chmod = chmodFix(fs.chmod);
      fs.fchmod = chmodFix(fs.fchmod);
      fs.lchmod = chmodFix(fs.lchmod);
      fs.chownSync = chownFixSync(fs.chownSync);
      fs.fchownSync = chownFixSync(fs.fchownSync);
      fs.lchownSync = chownFixSync(fs.lchownSync);
      fs.chmodSync = chmodFixSync(fs.chmodSync);
      fs.fchmodSync = chmodFixSync(fs.fchmodSync);
      fs.lchmodSync = chmodFixSync(fs.lchmodSync);
      fs.stat = statFix(fs.stat);
      fs.fstat = statFix(fs.fstat);
      fs.lstat = statFix(fs.lstat);
      fs.statSync = statFixSync(fs.statSync);
      fs.fstatSync = statFixSync(fs.fstatSync);
      fs.lstatSync = statFixSync(fs.lstatSync);
      if (fs.chmod && !fs.lchmod) {
        fs.lchmod = function(path, mode, cb) {
          if (cb) process.nextTick(cb);
        };
        fs.lchmodSync = function() {
        };
      }
      if (fs.chown && !fs.lchown) {
        fs.lchown = function(path, uid, gid, cb) {
          if (cb) process.nextTick(cb);
        };
        fs.lchownSync = function() {
        };
      }
      if (platform === "win32") {
        fs.rename = typeof fs.rename !== "function" ? fs.rename : (function(fs$rename) {
          function rename(from, to, cb) {
            var start = Date.now();
            var backoff = 0;
            fs$rename(from, to, function CB(er) {
              if (er && (er.code === "EACCES" || er.code === "EPERM" || er.code === "EBUSY") && Date.now() - start < 6e4) {
                setTimeout(function() {
                  fs.stat(to, function(stater, st) {
                    if (stater && stater.code === "ENOENT")
                      fs$rename(from, to, CB);
                    else
                      cb(er);
                  });
                }, backoff);
                if (backoff < 100)
                  backoff += 10;
                return;
              }
              if (cb) cb(er);
            });
          }
          if (Object.setPrototypeOf) Object.setPrototypeOf(rename, fs$rename);
          return rename;
        })(fs.rename);
      }
      fs.read = typeof fs.read !== "function" ? fs.read : (function(fs$read) {
        function read(fd, buffer, offset, length, position, callback_) {
          var callback;
          if (callback_ && typeof callback_ === "function") {
            var eagCounter = 0;
            callback = function(er, _, __) {
              if (er && er.code === "EAGAIN" && eagCounter < 10) {
                eagCounter++;
                return fs$read.call(fs, fd, buffer, offset, length, position, callback);
              }
              callback_.apply(this, arguments);
            };
          }
          return fs$read.call(fs, fd, buffer, offset, length, position, callback);
        }
        if (Object.setPrototypeOf) Object.setPrototypeOf(read, fs$read);
        return read;
      })(fs.read);
      fs.readSync = typeof fs.readSync !== "function" ? fs.readSync : /* @__PURE__ */ (function(fs$readSync) {
        return function(fd, buffer, offset, length, position) {
          var eagCounter = 0;
          while (true) {
            try {
              return fs$readSync.call(fs, fd, buffer, offset, length, position);
            } catch (er) {
              if (er.code === "EAGAIN" && eagCounter < 10) {
                eagCounter++;
                continue;
              }
              throw er;
            }
          }
        };
      })(fs.readSync);
      function patchLchmod(fs2) {
        fs2.lchmod = function(path, mode, callback) {
          fs2.open(
            path,
            constants.O_WRONLY | constants.O_SYMLINK,
            mode,
            function(err, fd) {
              if (err) {
                if (callback) callback(err);
                return;
              }
              fs2.fchmod(fd, mode, function(err2) {
                fs2.close(fd, function(err22) {
                  if (callback) callback(err2 || err22);
                });
              });
            }
          );
        };
        fs2.lchmodSync = function(path, mode) {
          var fd = fs2.openSync(path, constants.O_WRONLY | constants.O_SYMLINK, mode);
          var threw = true;
          var ret;
          try {
            ret = fs2.fchmodSync(fd, mode);
            threw = false;
          } finally {
            if (threw) {
              try {
                fs2.closeSync(fd);
              } catch (er) {
              }
            } else {
              fs2.closeSync(fd);
            }
          }
          return ret;
        };
      }
      function patchLutimes(fs2) {
        if (constants.hasOwnProperty("O_SYMLINK") && fs2.futimes) {
          fs2.lutimes = function(path, at, mt, cb) {
            fs2.open(path, constants.O_SYMLINK, function(er, fd) {
              if (er) {
                if (cb) cb(er);
                return;
              }
              fs2.futimes(fd, at, mt, function(er2) {
                fs2.close(fd, function(er22) {
                  if (cb) cb(er2 || er22);
                });
              });
            });
          };
          fs2.lutimesSync = function(path, at, mt) {
            var fd = fs2.openSync(path, constants.O_SYMLINK);
            var ret;
            var threw = true;
            try {
              ret = fs2.futimesSync(fd, at, mt);
              threw = false;
            } finally {
              if (threw) {
                try {
                  fs2.closeSync(fd);
                } catch (er) {
                }
              } else {
                fs2.closeSync(fd);
              }
            }
            return ret;
          };
        } else if (fs2.futimes) {
          fs2.lutimes = function(_a, _b, _c, cb) {
            if (cb) process.nextTick(cb);
          };
          fs2.lutimesSync = function() {
          };
        }
      }
      function chmodFix(orig) {
        if (!orig) return orig;
        return function(target, mode, cb) {
          return orig.call(fs, target, mode, function(er) {
            if (chownErOk(er)) er = null;
            if (cb) cb.apply(this, arguments);
          });
        };
      }
      function chmodFixSync(orig) {
        if (!orig) return orig;
        return function(target, mode) {
          try {
            return orig.call(fs, target, mode);
          } catch (er) {
            if (!chownErOk(er)) throw er;
          }
        };
      }
      function chownFix(orig) {
        if (!orig) return orig;
        return function(target, uid, gid, cb) {
          return orig.call(fs, target, uid, gid, function(er) {
            if (chownErOk(er)) er = null;
            if (cb) cb.apply(this, arguments);
          });
        };
      }
      function chownFixSync(orig) {
        if (!orig) return orig;
        return function(target, uid, gid) {
          try {
            return orig.call(fs, target, uid, gid);
          } catch (er) {
            if (!chownErOk(er)) throw er;
          }
        };
      }
      function statFix(orig) {
        if (!orig) return orig;
        return function(target, options, cb) {
          if (typeof options === "function") {
            cb = options;
            options = null;
          }
          function callback(er, stats) {
            if (stats) {
              if (stats.uid < 0) stats.uid += 4294967296;
              if (stats.gid < 0) stats.gid += 4294967296;
            }
            if (cb) cb.apply(this, arguments);
          }
          return options ? orig.call(fs, target, options, callback) : orig.call(fs, target, callback);
        };
      }
      function statFixSync(orig) {
        if (!orig) return orig;
        return function(target, options) {
          var stats = options ? orig.call(fs, target, options) : orig.call(fs, target);
          if (stats) {
            if (stats.uid < 0) stats.uid += 4294967296;
            if (stats.gid < 0) stats.gid += 4294967296;
          }
          return stats;
        };
      }
      function chownErOk(er) {
        if (!er)
          return true;
        if (er.code === "ENOSYS")
          return true;
        var nonroot = !process.getuid || process.getuid() !== 0;
        if (nonroot) {
          if (er.code === "EINVAL" || er.code === "EPERM")
            return true;
        }
        return false;
      }
    }
  }
});

// ../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/legacy-streams.js
var require_legacy_streams = __commonJS({
  "../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/legacy-streams.js"(exports2, module2) {
    var Stream = require("stream").Stream;
    module2.exports = legacy;
    function legacy(fs) {
      return {
        ReadStream,
        WriteStream
      };
      function ReadStream(path, options) {
        if (!(this instanceof ReadStream)) return new ReadStream(path, options);
        Stream.call(this);
        var self2 = this;
        this.path = path;
        this.fd = null;
        this.readable = true;
        this.paused = false;
        this.flags = "r";
        this.mode = 438;
        this.bufferSize = 64 * 1024;
        options = options || {};
        var keys = Object.keys(options);
        for (var index = 0, length = keys.length; index < length; index++) {
          var key = keys[index];
          this[key] = options[key];
        }
        if (this.encoding) this.setEncoding(this.encoding);
        if (this.start !== void 0) {
          if ("number" !== typeof this.start) {
            throw TypeError("start must be a Number");
          }
          if (this.end === void 0) {
            this.end = Infinity;
          } else if ("number" !== typeof this.end) {
            throw TypeError("end must be a Number");
          }
          if (this.start > this.end) {
            throw new Error("start must be <= end");
          }
          this.pos = this.start;
        }
        if (this.fd !== null) {
          process.nextTick(function() {
            self2._read();
          });
          return;
        }
        fs.open(this.path, this.flags, this.mode, function(err, fd) {
          if (err) {
            self2.emit("error", err);
            self2.readable = false;
            return;
          }
          self2.fd = fd;
          self2.emit("open", fd);
          self2._read();
        });
      }
      function WriteStream(path, options) {
        if (!(this instanceof WriteStream)) return new WriteStream(path, options);
        Stream.call(this);
        this.path = path;
        this.fd = null;
        this.writable = true;
        this.flags = "w";
        this.encoding = "binary";
        this.mode = 438;
        this.bytesWritten = 0;
        options = options || {};
        var keys = Object.keys(options);
        for (var index = 0, length = keys.length; index < length; index++) {
          var key = keys[index];
          this[key] = options[key];
        }
        if (this.start !== void 0) {
          if ("number" !== typeof this.start) {
            throw TypeError("start must be a Number");
          }
          if (this.start < 0) {
            throw new Error("start must be >= zero");
          }
          this.pos = this.start;
        }
        this.busy = false;
        this._queue = [];
        if (this.fd === null) {
          this._open = fs.open;
          this._queue.push([this._open, this.path, this.flags, this.mode, void 0]);
          this.flush();
        }
      }
    }
  }
});

// ../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/clone.js
var require_clone = __commonJS({
  "../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/clone.js"(exports2, module2) {
    "use strict";
    module2.exports = clone;
    var getPrototypeOf = Object.getPrototypeOf || function(obj) {
      return obj.__proto__;
    };
    function clone(obj) {
      if (obj === null || typeof obj !== "object")
        return obj;
      if (obj instanceof Object)
        var copy = { __proto__: getPrototypeOf(obj) };
      else
        var copy = /* @__PURE__ */ Object.create(null);
      Object.getOwnPropertyNames(obj).forEach(function(key) {
        Object.defineProperty(copy, key, Object.getOwnPropertyDescriptor(obj, key));
      });
      return copy;
    }
  }
});

// ../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/graceful-fs.js
var require_graceful_fs = __commonJS({
  "../node_modules/.pnpm/graceful-fs@4.2.11_patch_hash=68ebc232025360cb3dcd3081f4067f4e9fc022ab6b6f71a3230e86c7a5b337d1/node_modules/graceful-fs/graceful-fs.js"(exports2, module2) {
    var fs = require("fs");
    var polyfills = require_polyfills();
    var legacy = require_legacy_streams();
    var clone = require_clone();
    var util = require("util");
    var gracefulQueue;
    var previousSymbol;
    if (typeof Symbol === "function" && typeof Symbol.for === "function") {
      gracefulQueue = Symbol.for("graceful-fs.queue");
      previousSymbol = Symbol.for("graceful-fs.previous");
    } else {
      gracefulQueue = "___graceful-fs.queue";
      previousSymbol = "___graceful-fs.previous";
    }
    function noop() {
    }
    function publishQueue(context, queue2) {
      Object.defineProperty(context, gracefulQueue, {
        get: function() {
          return queue2;
        }
      });
    }
    var debug = noop;
    if (util.debuglog)
      debug = util.debuglog("gfs4");
    else if (/\bgfs4\b/i.test(process.env.NODE_DEBUG || ""))
      debug = function() {
        var m = util.format.apply(util, arguments);
        m = "GFS4: " + m.split(/\n/).join("\nGFS4: ");
        console.error(m);
      };
    if (!fs[gracefulQueue]) {
      queue = global[gracefulQueue] || [];
      publishQueue(fs, queue);
      fs.close = (function(fs$close) {
        function close(fd, cb) {
          return fs$close.call(fs, fd, function(err) {
            if (!err) {
              resetQueue();
            }
            if (typeof cb === "function")
              cb.apply(this, arguments);
          });
        }
        Object.defineProperty(close, previousSymbol, {
          value: fs$close
        });
        return close;
      })(fs.close);
      fs.closeSync = (function(fs$closeSync) {
        function closeSync(fd) {
          fs$closeSync.apply(fs, arguments);
          resetQueue();
        }
        Object.defineProperty(closeSync, previousSymbol, {
          value: fs$closeSync
        });
        return closeSync;
      })(fs.closeSync);
      if (/\bgfs4\b/i.test(process.env.NODE_DEBUG || "")) {
        process.on("exit", function() {
          debug(fs[gracefulQueue]);
          require("assert").equal(fs[gracefulQueue].length, 0);
        });
      }
    }
    var queue;
    if (!global[gracefulQueue]) {
      publishQueue(global, fs[gracefulQueue]);
    }
    module2.exports = patch(clone(fs));
    if (process.env.TEST_GRACEFUL_FS_GLOBAL_PATCH && !fs.__patched) {
      module2.exports = patch(fs);
      fs.__patched = true;
    }
    function patch(fs2) {
      polyfills(fs2);
      fs2.gracefulify = patch;
      fs2.createReadStream = createReadStream;
      fs2.createWriteStream = createWriteStream;
      var fs$readFile = fs2.readFile;
      fs2.readFile = readFile;
      function readFile(path, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        return go$readFile(path, options, cb);
        function go$readFile(path2, options2, cb2, startTime) {
          return fs$readFile(path2, options2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$readFile, [path2, options2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$writeFile = fs2.writeFile;
      fs2.writeFile = writeFile;
      function writeFile(path, data, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        return go$writeFile(path, data, options, cb);
        function go$writeFile(path2, data2, options2, cb2, startTime) {
          return fs$writeFile(path2, data2, options2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$writeFile, [path2, data2, options2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$appendFile = fs2.appendFile;
      if (fs$appendFile)
        fs2.appendFile = appendFile;
      function appendFile(path, data, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        return go$appendFile(path, data, options, cb);
        function go$appendFile(path2, data2, options2, cb2, startTime) {
          return fs$appendFile(path2, data2, options2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$appendFile, [path2, data2, options2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$copyFile = fs2.copyFile;
      if (fs$copyFile)
        fs2.copyFile = copyFile;
      function copyFile(src, dest, flags, cb) {
        if (typeof flags === "function") {
          cb = flags;
          flags = 0;
        }
        return go$copyFile(src, dest, flags, cb);
        function go$copyFile(src2, dest2, flags2, cb2, startTime) {
          return fs$copyFile(src2, dest2, flags2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE" || err.code === "EBUSY"))
              enqueue([go$copyFile, [src2, dest2, flags2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$readdir = fs2.readdir;
      fs2.readdir = readdir;
      var noReaddirOptionVersions = /^v[0-5]\./;
      function readdir(path, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        var go$readdir = noReaddirOptionVersions.test(process.version) ? function go$readdir2(path2, options2, cb2, startTime) {
          return fs$readdir(path2, fs$readdirCallback(
            path2,
            options2,
            cb2,
            startTime
          ));
        } : function go$readdir2(path2, options2, cb2, startTime) {
          return fs$readdir(path2, options2, fs$readdirCallback(
            path2,
            options2,
            cb2,
            startTime
          ));
        };
        return go$readdir(path, options, cb);
        function fs$readdirCallback(path2, options2, cb2, startTime) {
          return function(err, files) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([
                go$readdir,
                [path2, options2, cb2],
                err,
                startTime || Date.now(),
                Date.now()
              ]);
            else {
              if (files && files.sort)
                files.sort();
              if (typeof cb2 === "function")
                cb2.call(this, err, files);
            }
          };
        }
      }
      if (process.version.substr(0, 4) === "v0.8") {
        var legStreams = legacy(fs2);
        ReadStream = legStreams.ReadStream;
        WriteStream = legStreams.WriteStream;
      }
      var fs$ReadStream = fs2.ReadStream;
      if (fs$ReadStream) {
        ReadStream.prototype = Object.create(fs$ReadStream.prototype);
        ReadStream.prototype.open = ReadStream$open;
      }
      var fs$WriteStream = fs2.WriteStream;
      if (fs$WriteStream) {
        WriteStream.prototype = Object.create(fs$WriteStream.prototype);
        WriteStream.prototype.open = WriteStream$open;
      }
      Object.defineProperty(fs2, "ReadStream", {
        get: function() {
          return ReadStream;
        },
        set: function(val) {
          ReadStream = val;
        },
        enumerable: true,
        configurable: true
      });
      Object.defineProperty(fs2, "WriteStream", {
        get: function() {
          return WriteStream;
        },
        set: function(val) {
          WriteStream = val;
        },
        enumerable: true,
        configurable: true
      });
      var FileReadStream = ReadStream;
      Object.defineProperty(fs2, "FileReadStream", {
        get: function() {
          return FileReadStream;
        },
        set: function(val) {
          FileReadStream = val;
        },
        enumerable: true,
        configurable: true
      });
      var FileWriteStream = WriteStream;
      Object.defineProperty(fs2, "FileWriteStream", {
        get: function() {
          return FileWriteStream;
        },
        set: function(val) {
          FileWriteStream = val;
        },
        enumerable: true,
        configurable: true
      });
      function ReadStream(path, options) {
        if (this instanceof ReadStream)
          return fs$ReadStream.apply(this, arguments), this;
        else
          return ReadStream.apply(Object.create(ReadStream.prototype), arguments);
      }
      function ReadStream$open() {
        var that = this;
        open(that.path, that.flags, that.mode, function(err, fd) {
          if (err) {
            if (that.autoClose)
              that.destroy();
            that.emit("error", err);
          } else {
            that.fd = fd;
            that.emit("open", fd);
            that.read();
          }
        });
      }
      function WriteStream(path, options) {
        if (this instanceof WriteStream)
          return fs$WriteStream.apply(this, arguments), this;
        else
          return WriteStream.apply(Object.create(WriteStream.prototype), arguments);
      }
      function WriteStream$open() {
        var that = this;
        open(that.path, that.flags, that.mode, function(err, fd) {
          if (err) {
            that.destroy();
            that.emit("error", err);
          } else {
            that.fd = fd;
            that.emit("open", fd);
          }
        });
      }
      function createReadStream(path, options) {
        return new fs2.ReadStream(path, options);
      }
      function createWriteStream(path, options) {
        return new fs2.WriteStream(path, options);
      }
      var fs$open = fs2.open;
      fs2.open = open;
      function open(path, flags, mode, cb) {
        if (typeof mode === "function")
          cb = mode, mode = null;
        return go$open(path, flags, mode, cb);
        function go$open(path2, flags2, mode2, cb2, startTime) {
          return fs$open(path2, flags2, mode2, function(err, fd) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$open, [path2, flags2, mode2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      return fs2;
    }
    function enqueue(elem) {
      debug("ENQUEUE", elem[0].name, elem[1]);
      fs[gracefulQueue].push(elem);
      retry();
    }
    var retryTimer;
    function resetQueue() {
      var now = Date.now();
      for (var i = 0; i < fs[gracefulQueue].length; ++i) {
        if (fs[gracefulQueue][i].length > 2) {
          fs[gracefulQueue][i][3] = now;
          fs[gracefulQueue][i][4] = now;
        }
      }
      retry();
    }
    function retry() {
      clearTimeout(retryTimer);
      retryTimer = void 0;
      if (fs[gracefulQueue].length === 0)
        return;
      var elem = fs[gracefulQueue].shift();
      var fn = elem[0];
      var args = elem[1];
      var err = elem[2];
      var startTime = elem[3];
      var lastTime = elem[4];
      if (startTime === void 0) {
        debug("RETRY", fn.name, args);
        fn.apply(null, args);
      } else if (Date.now() - startTime >= 6e4) {
        debug("TIMEOUT", fn.name, args);
        var cb = args.pop();
        if (typeof cb === "function")
          cb.call(null, err);
      } else {
        var sinceAttempt = Date.now() - lastTime;
        var sinceStart = Math.max(lastTime - startTime, 1);
        var desiredDelay = Math.min(sinceStart * 1.2, 100);
        if (sinceAttempt >= desiredDelay) {
          debug("RETRY", fn.name, args);
          fn.apply(null, args.concat([startTime]));
        } else {
          fs[gracefulQueue].push(elem);
        }
      }
      if (retryTimer === void 0) {
        retryTimer = setTimeout(retry, 0);
      }
    }
  }
});

// ../fs/graceful-fs/lib/index.js
var require_lib = __commonJS({
  "../fs/graceful-fs/lib/index.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __setModuleDefault = exports2 && exports2.__setModuleDefault || (Object.create ? (function(o, v) {
      Object.defineProperty(o, "default", { enumerable: true, value: v });
    }) : function(o, v) {
      o["default"] = v;
    });
    var __importStar = exports2 && exports2.__importStar || function(mod) {
      if (mod && mod.__esModule) return mod;
      var result = {};
      if (mod != null) {
        for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
      }
      __setModuleDefault(result, mod);
      return result;
    };
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    var util_1 = __importStar(require("util"));
    var graceful_fs_1 = __importDefault(require_graceful_fs());
    exports2.default = {
      copyFile: (0, util_1.promisify)(graceful_fs_1.default.copyFile),
      copyFileSync: withEagainRetry(graceful_fs_1.default.copyFileSync),
      createReadStream: graceful_fs_1.default.createReadStream,
      link: (0, util_1.promisify)(graceful_fs_1.default.link),
      linkSync: withEagainRetry(graceful_fs_1.default.linkSync),
      mkdir: (0, util_1.promisify)(graceful_fs_1.default.mkdir),
      mkdirSync: withEagainRetry(graceful_fs_1.default.mkdirSync),
      renameSync: withEagainRetry(graceful_fs_1.default.renameSync),
      readFile: (0, util_1.promisify)(graceful_fs_1.default.readFile),
      readFileSync: graceful_fs_1.default.readFileSync,
      readdirSync: graceful_fs_1.default.readdirSync,
      stat: (0, util_1.promisify)(graceful_fs_1.default.stat),
      statSync: graceful_fs_1.default.statSync,
      unlinkSync: graceful_fs_1.default.unlinkSync,
      writeFile: (0, util_1.promisify)(graceful_fs_1.default.writeFile),
      writeFileSync: withEagainRetry(graceful_fs_1.default.writeFileSync)
    };
    function withEagainRetry(fn, maxRetries = 15) {
      return (...args) => {
        let attempts = 0;
        while (attempts <= maxRetries) {
          try {
            return fn(...args);
          } catch (err) {
            if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "EAGAIN" && attempts < maxRetries) {
              attempts++;
              const delay = Math.min(Math.pow(2, attempts), 300);
              Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delay);
              continue;
            }
            throw err;
          }
        }
        throw new Error("Unreachable");
      };
    }
  }
});

// ../node_modules/.pnpm/minipass@7.1.2/node_modules/minipass/dist/commonjs/index.js
var require_commonjs = __commonJS({
  "../node_modules/.pnpm/minipass@7.1.2/node_modules/minipass/dist/commonjs/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.Minipass = exports2.isWritable = exports2.isReadable = exports2.isStream = void 0;
    var proc = typeof process === "object" && process ? process : {
      stdout: null,
      stderr: null
    };
    var node_events_1 = require("node:events");
    var node_stream_1 = __importDefault(require("node:stream"));
    var node_string_decoder_1 = require("node:string_decoder");
    var isStream = (s) => !!s && typeof s === "object" && (s instanceof Minipass || s instanceof node_stream_1.default || (0, exports2.isReadable)(s) || (0, exports2.isWritable)(s));
    exports2.isStream = isStream;
    var isReadable = (s) => !!s && typeof s === "object" && s instanceof node_events_1.EventEmitter && typeof s.pipe === "function" && // node core Writable streams have a pipe() method, but it throws
    s.pipe !== node_stream_1.default.Writable.prototype.pipe;
    exports2.isReadable = isReadable;
    var isWritable = (s) => !!s && typeof s === "object" && s instanceof node_events_1.EventEmitter && typeof s.write === "function" && typeof s.end === "function";
    exports2.isWritable = isWritable;
    var EOF = Symbol("EOF");
    var MAYBE_EMIT_END = Symbol("maybeEmitEnd");
    var EMITTED_END = Symbol("emittedEnd");
    var EMITTING_END = Symbol("emittingEnd");
    var EMITTED_ERROR = Symbol("emittedError");
    var CLOSED = Symbol("closed");
    var READ = Symbol("read");
    var FLUSH = Symbol("flush");
    var FLUSHCHUNK = Symbol("flushChunk");
    var ENCODING = Symbol("encoding");
    var DECODER = Symbol("decoder");
    var FLOWING = Symbol("flowing");
    var PAUSED = Symbol("paused");
    var RESUME = Symbol("resume");
    var BUFFER = Symbol("buffer");
    var PIPES = Symbol("pipes");
    var BUFFERLENGTH = Symbol("bufferLength");
    var BUFFERPUSH = Symbol("bufferPush");
    var BUFFERSHIFT = Symbol("bufferShift");
    var OBJECTMODE = Symbol("objectMode");
    var DESTROYED = Symbol("destroyed");
    var ERROR = Symbol("error");
    var EMITDATA = Symbol("emitData");
    var EMITEND = Symbol("emitEnd");
    var EMITEND2 = Symbol("emitEnd2");
    var ASYNC = Symbol("async");
    var ABORT = Symbol("abort");
    var ABORTED = Symbol("aborted");
    var SIGNAL = Symbol("signal");
    var DATALISTENERS = Symbol("dataListeners");
    var DISCARDED = Symbol("discarded");
    var defer = (fn) => Promise.resolve().then(fn);
    var nodefer = (fn) => fn();
    var isEndish = (ev) => ev === "end" || ev === "finish" || ev === "prefinish";
    var isArrayBufferLike = (b) => b instanceof ArrayBuffer || !!b && typeof b === "object" && b.constructor && b.constructor.name === "ArrayBuffer" && b.byteLength >= 0;
    var isArrayBufferView = (b) => !Buffer.isBuffer(b) && ArrayBuffer.isView(b);
    var Pipe = class {
      src;
      dest;
      opts;
      ondrain;
      constructor(src, dest, opts) {
        this.src = src;
        this.dest = dest;
        this.opts = opts;
        this.ondrain = () => src[RESUME]();
        this.dest.on("drain", this.ondrain);
      }
      unpipe() {
        this.dest.removeListener("drain", this.ondrain);
      }
      // only here for the prototype
      /* c8 ignore start */
      proxyErrors(_er) {
      }
      /* c8 ignore stop */
      end() {
        this.unpipe();
        if (this.opts.end)
          this.dest.end();
      }
    };
    var PipeProxyErrors = class extends Pipe {
      unpipe() {
        this.src.removeListener("error", this.proxyErrors);
        super.unpipe();
      }
      constructor(src, dest, opts) {
        super(src, dest, opts);
        this.proxyErrors = (er) => dest.emit("error", er);
        src.on("error", this.proxyErrors);
      }
    };
    var isObjectModeOptions = (o) => !!o.objectMode;
    var isEncodingOptions = (o) => !o.objectMode && !!o.encoding && o.encoding !== "buffer";
    var Minipass = class extends node_events_1.EventEmitter {
      [FLOWING] = false;
      [PAUSED] = false;
      [PIPES] = [];
      [BUFFER] = [];
      [OBJECTMODE];
      [ENCODING];
      [ASYNC];
      [DECODER];
      [EOF] = false;
      [EMITTED_END] = false;
      [EMITTING_END] = false;
      [CLOSED] = false;
      [EMITTED_ERROR] = null;
      [BUFFERLENGTH] = 0;
      [DESTROYED] = false;
      [SIGNAL];
      [ABORTED] = false;
      [DATALISTENERS] = 0;
      [DISCARDED] = false;
      /**
       * true if the stream can be written
       */
      writable = true;
      /**
       * true if the stream can be read
       */
      readable = true;
      /**
       * If `RType` is Buffer, then options do not need to be provided.
       * Otherwise, an options object must be provided to specify either
       * {@link Minipass.SharedOptions.objectMode} or
       * {@link Minipass.SharedOptions.encoding}, as appropriate.
       */
      constructor(...args) {
        const options = args[0] || {};
        super();
        if (options.objectMode && typeof options.encoding === "string") {
          throw new TypeError("Encoding and objectMode may not be used together");
        }
        if (isObjectModeOptions(options)) {
          this[OBJECTMODE] = true;
          this[ENCODING] = null;
        } else if (isEncodingOptions(options)) {
          this[ENCODING] = options.encoding;
          this[OBJECTMODE] = false;
        } else {
          this[OBJECTMODE] = false;
          this[ENCODING] = null;
        }
        this[ASYNC] = !!options.async;
        this[DECODER] = this[ENCODING] ? new node_string_decoder_1.StringDecoder(this[ENCODING]) : null;
        if (options && options.debugExposeBuffer === true) {
          Object.defineProperty(this, "buffer", { get: () => this[BUFFER] });
        }
        if (options && options.debugExposePipes === true) {
          Object.defineProperty(this, "pipes", { get: () => this[PIPES] });
        }
        const { signal } = options;
        if (signal) {
          this[SIGNAL] = signal;
          if (signal.aborted) {
            this[ABORT]();
          } else {
            signal.addEventListener("abort", () => this[ABORT]());
          }
        }
      }
      /**
       * The amount of data stored in the buffer waiting to be read.
       *
       * For Buffer strings, this will be the total byte length.
       * For string encoding streams, this will be the string character length,
       * according to JavaScript's `string.length` logic.
       * For objectMode streams, this is a count of the items waiting to be
       * emitted.
       */
      get bufferLength() {
        return this[BUFFERLENGTH];
      }
      /**
       * The `BufferEncoding` currently in use, or `null`
       */
      get encoding() {
        return this[ENCODING];
      }
      /**
       * @deprecated - This is a read only property
       */
      set encoding(_enc) {
        throw new Error("Encoding must be set at instantiation time");
      }
      /**
       * @deprecated - Encoding may only be set at instantiation time
       */
      setEncoding(_enc) {
        throw new Error("Encoding must be set at instantiation time");
      }
      /**
       * True if this is an objectMode stream
       */
      get objectMode() {
        return this[OBJECTMODE];
      }
      /**
       * @deprecated - This is a read-only property
       */
      set objectMode(_om) {
        throw new Error("objectMode must be set at instantiation time");
      }
      /**
       * true if this is an async stream
       */
      get ["async"]() {
        return this[ASYNC];
      }
      /**
       * Set to true to make this stream async.
       *
       * Once set, it cannot be unset, as this would potentially cause incorrect
       * behavior.  Ie, a sync stream can be made async, but an async stream
       * cannot be safely made sync.
       */
      set ["async"](a) {
        this[ASYNC] = this[ASYNC] || !!a;
      }
      // drop everything and get out of the flow completely
      [ABORT]() {
        this[ABORTED] = true;
        this.emit("abort", this[SIGNAL]?.reason);
        this.destroy(this[SIGNAL]?.reason);
      }
      /**
       * True if the stream has been aborted.
       */
      get aborted() {
        return this[ABORTED];
      }
      /**
       * No-op setter. Stream aborted status is set via the AbortSignal provided
       * in the constructor options.
       */
      set aborted(_) {
      }
      write(chunk, encoding, cb) {
        if (this[ABORTED])
          return false;
        if (this[EOF])
          throw new Error("write after end");
        if (this[DESTROYED]) {
          this.emit("error", Object.assign(new Error("Cannot call write after a stream was destroyed"), { code: "ERR_STREAM_DESTROYED" }));
          return true;
        }
        if (typeof encoding === "function") {
          cb = encoding;
          encoding = "utf8";
        }
        if (!encoding)
          encoding = "utf8";
        const fn = this[ASYNC] ? defer : nodefer;
        if (!this[OBJECTMODE] && !Buffer.isBuffer(chunk)) {
          if (isArrayBufferView(chunk)) {
            chunk = Buffer.from(chunk.buffer, chunk.byteOffset, chunk.byteLength);
          } else if (isArrayBufferLike(chunk)) {
            chunk = Buffer.from(chunk);
          } else if (typeof chunk !== "string") {
            throw new Error("Non-contiguous data written to non-objectMode stream");
          }
        }
        if (this[OBJECTMODE]) {
          if (this[FLOWING] && this[BUFFERLENGTH] !== 0)
            this[FLUSH](true);
          if (this[FLOWING])
            this.emit("data", chunk);
          else
            this[BUFFERPUSH](chunk);
          if (this[BUFFERLENGTH] !== 0)
            this.emit("readable");
          if (cb)
            fn(cb);
          return this[FLOWING];
        }
        if (!chunk.length) {
          if (this[BUFFERLENGTH] !== 0)
            this.emit("readable");
          if (cb)
            fn(cb);
          return this[FLOWING];
        }
        if (typeof chunk === "string" && // unless it is a string already ready for us to use
        !(encoding === this[ENCODING] && !this[DECODER]?.lastNeed)) {
          chunk = Buffer.from(chunk, encoding);
        }
        if (Buffer.isBuffer(chunk) && this[ENCODING]) {
          chunk = this[DECODER].write(chunk);
        }
        if (this[FLOWING] && this[BUFFERLENGTH] !== 0)
          this[FLUSH](true);
        if (this[FLOWING])
          this.emit("data", chunk);
        else
          this[BUFFERPUSH](chunk);
        if (this[BUFFERLENGTH] !== 0)
          this.emit("readable");
        if (cb)
          fn(cb);
        return this[FLOWING];
      }
      /**
       * Low-level explicit read method.
       *
       * In objectMode, the argument is ignored, and one item is returned if
       * available.
       *
       * `n` is the number of bytes (or in the case of encoding streams,
       * characters) to consume. If `n` is not provided, then the entire buffer
       * is returned, or `null` is returned if no data is available.
       *
       * If `n` is greater that the amount of data in the internal buffer,
       * then `null` is returned.
       */
      read(n) {
        if (this[DESTROYED])
          return null;
        this[DISCARDED] = false;
        if (this[BUFFERLENGTH] === 0 || n === 0 || n && n > this[BUFFERLENGTH]) {
          this[MAYBE_EMIT_END]();
          return null;
        }
        if (this[OBJECTMODE])
          n = null;
        if (this[BUFFER].length > 1 && !this[OBJECTMODE]) {
          this[BUFFER] = [
            this[ENCODING] ? this[BUFFER].join("") : Buffer.concat(this[BUFFER], this[BUFFERLENGTH])
          ];
        }
        const ret = this[READ](n || null, this[BUFFER][0]);
        this[MAYBE_EMIT_END]();
        return ret;
      }
      [READ](n, chunk) {
        if (this[OBJECTMODE])
          this[BUFFERSHIFT]();
        else {
          const c = chunk;
          if (n === c.length || n === null)
            this[BUFFERSHIFT]();
          else if (typeof c === "string") {
            this[BUFFER][0] = c.slice(n);
            chunk = c.slice(0, n);
            this[BUFFERLENGTH] -= n;
          } else {
            this[BUFFER][0] = c.subarray(n);
            chunk = c.subarray(0, n);
            this[BUFFERLENGTH] -= n;
          }
        }
        this.emit("data", chunk);
        if (!this[BUFFER].length && !this[EOF])
          this.emit("drain");
        return chunk;
      }
      end(chunk, encoding, cb) {
        if (typeof chunk === "function") {
          cb = chunk;
          chunk = void 0;
        }
        if (typeof encoding === "function") {
          cb = encoding;
          encoding = "utf8";
        }
        if (chunk !== void 0)
          this.write(chunk, encoding);
        if (cb)
          this.once("end", cb);
        this[EOF] = true;
        this.writable = false;
        if (this[FLOWING] || !this[PAUSED])
          this[MAYBE_EMIT_END]();
        return this;
      }
      // don't let the internal resume be overwritten
      [RESUME]() {
        if (this[DESTROYED])
          return;
        if (!this[DATALISTENERS] && !this[PIPES].length) {
          this[DISCARDED] = true;
        }
        this[PAUSED] = false;
        this[FLOWING] = true;
        this.emit("resume");
        if (this[BUFFER].length)
          this[FLUSH]();
        else if (this[EOF])
          this[MAYBE_EMIT_END]();
        else
          this.emit("drain");
      }
      /**
       * Resume the stream if it is currently in a paused state
       *
       * If called when there are no pipe destinations or `data` event listeners,
       * this will place the stream in a "discarded" state, where all data will
       * be thrown away. The discarded state is removed if a pipe destination or
       * data handler is added, if pause() is called, or if any synchronous or
       * asynchronous iteration is started.
       */
      resume() {
        return this[RESUME]();
      }
      /**
       * Pause the stream
       */
      pause() {
        this[FLOWING] = false;
        this[PAUSED] = true;
        this[DISCARDED] = false;
      }
      /**
       * true if the stream has been forcibly destroyed
       */
      get destroyed() {
        return this[DESTROYED];
      }
      /**
       * true if the stream is currently in a flowing state, meaning that
       * any writes will be immediately emitted.
       */
      get flowing() {
        return this[FLOWING];
      }
      /**
       * true if the stream is currently in a paused state
       */
      get paused() {
        return this[PAUSED];
      }
      [BUFFERPUSH](chunk) {
        if (this[OBJECTMODE])
          this[BUFFERLENGTH] += 1;
        else
          this[BUFFERLENGTH] += chunk.length;
        this[BUFFER].push(chunk);
      }
      [BUFFERSHIFT]() {
        if (this[OBJECTMODE])
          this[BUFFERLENGTH] -= 1;
        else
          this[BUFFERLENGTH] -= this[BUFFER][0].length;
        return this[BUFFER].shift();
      }
      [FLUSH](noDrain = false) {
        do {
        } while (this[FLUSHCHUNK](this[BUFFERSHIFT]()) && this[BUFFER].length);
        if (!noDrain && !this[BUFFER].length && !this[EOF])
          this.emit("drain");
      }
      [FLUSHCHUNK](chunk) {
        this.emit("data", chunk);
        return this[FLOWING];
      }
      /**
       * Pipe all data emitted by this stream into the destination provided.
       *
       * Triggers the flow of data.
       */
      pipe(dest, opts) {
        if (this[DESTROYED])
          return dest;
        this[DISCARDED] = false;
        const ended = this[EMITTED_END];
        opts = opts || {};
        if (dest === proc.stdout || dest === proc.stderr)
          opts.end = false;
        else
          opts.end = opts.end !== false;
        opts.proxyErrors = !!opts.proxyErrors;
        if (ended) {
          if (opts.end)
            dest.end();
        } else {
          this[PIPES].push(!opts.proxyErrors ? new Pipe(this, dest, opts) : new PipeProxyErrors(this, dest, opts));
          if (this[ASYNC])
            defer(() => this[RESUME]());
          else
            this[RESUME]();
        }
        return dest;
      }
      /**
       * Fully unhook a piped destination stream.
       *
       * If the destination stream was the only consumer of this stream (ie,
       * there are no other piped destinations or `'data'` event listeners)
       * then the flow of data will stop until there is another consumer or
       * {@link Minipass#resume} is explicitly called.
       */
      unpipe(dest) {
        const p = this[PIPES].find((p2) => p2.dest === dest);
        if (p) {
          if (this[PIPES].length === 1) {
            if (this[FLOWING] && this[DATALISTENERS] === 0) {
              this[FLOWING] = false;
            }
            this[PIPES] = [];
          } else
            this[PIPES].splice(this[PIPES].indexOf(p), 1);
          p.unpipe();
        }
      }
      /**
       * Alias for {@link Minipass#on}
       */
      addListener(ev, handler) {
        return this.on(ev, handler);
      }
      /**
       * Mostly identical to `EventEmitter.on`, with the following
       * behavior differences to prevent data loss and unnecessary hangs:
       *
       * - Adding a 'data' event handler will trigger the flow of data
       *
       * - Adding a 'readable' event handler when there is data waiting to be read
       *   will cause 'readable' to be emitted immediately.
       *
       * - Adding an 'endish' event handler ('end', 'finish', etc.) which has
       *   already passed will cause the event to be emitted immediately and all
       *   handlers removed.
       *
       * - Adding an 'error' event handler after an error has been emitted will
       *   cause the event to be re-emitted immediately with the error previously
       *   raised.
       */
      on(ev, handler) {
        const ret = super.on(ev, handler);
        if (ev === "data") {
          this[DISCARDED] = false;
          this[DATALISTENERS]++;
          if (!this[PIPES].length && !this[FLOWING]) {
            this[RESUME]();
          }
        } else if (ev === "readable" && this[BUFFERLENGTH] !== 0) {
          super.emit("readable");
        } else if (isEndish(ev) && this[EMITTED_END]) {
          super.emit(ev);
          this.removeAllListeners(ev);
        } else if (ev === "error" && this[EMITTED_ERROR]) {
          const h = handler;
          if (this[ASYNC])
            defer(() => h.call(this, this[EMITTED_ERROR]));
          else
            h.call(this, this[EMITTED_ERROR]);
        }
        return ret;
      }
      /**
       * Alias for {@link Minipass#off}
       */
      removeListener(ev, handler) {
        return this.off(ev, handler);
      }
      /**
       * Mostly identical to `EventEmitter.off`
       *
       * If a 'data' event handler is removed, and it was the last consumer
       * (ie, there are no pipe destinations or other 'data' event listeners),
       * then the flow of data will stop until there is another consumer or
       * {@link Minipass#resume} is explicitly called.
       */
      off(ev, handler) {
        const ret = super.off(ev, handler);
        if (ev === "data") {
          this[DATALISTENERS] = this.listeners("data").length;
          if (this[DATALISTENERS] === 0 && !this[DISCARDED] && !this[PIPES].length) {
            this[FLOWING] = false;
          }
        }
        return ret;
      }
      /**
       * Mostly identical to `EventEmitter.removeAllListeners`
       *
       * If all 'data' event handlers are removed, and they were the last consumer
       * (ie, there are no pipe destinations), then the flow of data will stop
       * until there is another consumer or {@link Minipass#resume} is explicitly
       * called.
       */
      removeAllListeners(ev) {
        const ret = super.removeAllListeners(ev);
        if (ev === "data" || ev === void 0) {
          this[DATALISTENERS] = 0;
          if (!this[DISCARDED] && !this[PIPES].length) {
            this[FLOWING] = false;
          }
        }
        return ret;
      }
      /**
       * true if the 'end' event has been emitted
       */
      get emittedEnd() {
        return this[EMITTED_END];
      }
      [MAYBE_EMIT_END]() {
        if (!this[EMITTING_END] && !this[EMITTED_END] && !this[DESTROYED] && this[BUFFER].length === 0 && this[EOF]) {
          this[EMITTING_END] = true;
          this.emit("end");
          this.emit("prefinish");
          this.emit("finish");
          if (this[CLOSED])
            this.emit("close");
          this[EMITTING_END] = false;
        }
      }
      /**
       * Mostly identical to `EventEmitter.emit`, with the following
       * behavior differences to prevent data loss and unnecessary hangs:
       *
       * If the stream has been destroyed, and the event is something other
       * than 'close' or 'error', then `false` is returned and no handlers
       * are called.
       *
       * If the event is 'end', and has already been emitted, then the event
       * is ignored. If the stream is in a paused or non-flowing state, then
       * the event will be deferred until data flow resumes. If the stream is
       * async, then handlers will be called on the next tick rather than
       * immediately.
       *
       * If the event is 'close', and 'end' has not yet been emitted, then
       * the event will be deferred until after 'end' is emitted.
       *
       * If the event is 'error', and an AbortSignal was provided for the stream,
       * and there are no listeners, then the event is ignored, matching the
       * behavior of node core streams in the presense of an AbortSignal.
       *
       * If the event is 'finish' or 'prefinish', then all listeners will be
       * removed after emitting the event, to prevent double-firing.
       */
      emit(ev, ...args) {
        const data = args[0];
        if (ev !== "error" && ev !== "close" && ev !== DESTROYED && this[DESTROYED]) {
          return false;
        } else if (ev === "data") {
          return !this[OBJECTMODE] && !data ? false : this[ASYNC] ? (defer(() => this[EMITDATA](data)), true) : this[EMITDATA](data);
        } else if (ev === "end") {
          return this[EMITEND]();
        } else if (ev === "close") {
          this[CLOSED] = true;
          if (!this[EMITTED_END] && !this[DESTROYED])
            return false;
          const ret2 = super.emit("close");
          this.removeAllListeners("close");
          return ret2;
        } else if (ev === "error") {
          this[EMITTED_ERROR] = data;
          super.emit(ERROR, data);
          const ret2 = !this[SIGNAL] || this.listeners("error").length ? super.emit("error", data) : false;
          this[MAYBE_EMIT_END]();
          return ret2;
        } else if (ev === "resume") {
          const ret2 = super.emit("resume");
          this[MAYBE_EMIT_END]();
          return ret2;
        } else if (ev === "finish" || ev === "prefinish") {
          const ret2 = super.emit(ev);
          this.removeAllListeners(ev);
          return ret2;
        }
        const ret = super.emit(ev, ...args);
        this[MAYBE_EMIT_END]();
        return ret;
      }
      [EMITDATA](data) {
        for (const p of this[PIPES]) {
          if (p.dest.write(data) === false)
            this.pause();
        }
        const ret = this[DISCARDED] ? false : super.emit("data", data);
        this[MAYBE_EMIT_END]();
        return ret;
      }
      [EMITEND]() {
        if (this[EMITTED_END])
          return false;
        this[EMITTED_END] = true;
        this.readable = false;
        return this[ASYNC] ? (defer(() => this[EMITEND2]()), true) : this[EMITEND2]();
      }
      [EMITEND2]() {
        if (this[DECODER]) {
          const data = this[DECODER].end();
          if (data) {
            for (const p of this[PIPES]) {
              p.dest.write(data);
            }
            if (!this[DISCARDED])
              super.emit("data", data);
          }
        }
        for (const p of this[PIPES]) {
          p.end();
        }
        const ret = super.emit("end");
        this.removeAllListeners("end");
        return ret;
      }
      /**
       * Return a Promise that resolves to an array of all emitted data once
       * the stream ends.
       */
      async collect() {
        const buf = Object.assign([], {
          dataLength: 0
        });
        if (!this[OBJECTMODE])
          buf.dataLength = 0;
        const p = this.promise();
        this.on("data", (c) => {
          buf.push(c);
          if (!this[OBJECTMODE])
            buf.dataLength += c.length;
        });
        await p;
        return buf;
      }
      /**
       * Return a Promise that resolves to the concatenation of all emitted data
       * once the stream ends.
       *
       * Not allowed on objectMode streams.
       */
      async concat() {
        if (this[OBJECTMODE]) {
          throw new Error("cannot concat in objectMode");
        }
        const buf = await this.collect();
        return this[ENCODING] ? buf.join("") : Buffer.concat(buf, buf.dataLength);
      }
      /**
       * Return a void Promise that resolves once the stream ends.
       */
      async promise() {
        return new Promise((resolve, reject) => {
          this.on(DESTROYED, () => reject(new Error("stream destroyed")));
          this.on("error", (er) => reject(er));
          this.on("end", () => resolve());
        });
      }
      /**
       * Asynchronous `for await of` iteration.
       *
       * This will continue emitting all chunks until the stream terminates.
       */
      [Symbol.asyncIterator]() {
        this[DISCARDED] = false;
        let stopped = false;
        const stop = async () => {
          this.pause();
          stopped = true;
          return { value: void 0, done: true };
        };
        const next = () => {
          if (stopped)
            return stop();
          const res = this.read();
          if (res !== null)
            return Promise.resolve({ done: false, value: res });
          if (this[EOF])
            return stop();
          let resolve;
          let reject;
          const onerr = (er) => {
            this.off("data", ondata);
            this.off("end", onend);
            this.off(DESTROYED, ondestroy);
            stop();
            reject(er);
          };
          const ondata = (value) => {
            this.off("error", onerr);
            this.off("end", onend);
            this.off(DESTROYED, ondestroy);
            this.pause();
            resolve({ value, done: !!this[EOF] });
          };
          const onend = () => {
            this.off("error", onerr);
            this.off("data", ondata);
            this.off(DESTROYED, ondestroy);
            stop();
            resolve({ done: true, value: void 0 });
          };
          const ondestroy = () => onerr(new Error("stream destroyed"));
          return new Promise((res2, rej) => {
            reject = rej;
            resolve = res2;
            this.once(DESTROYED, ondestroy);
            this.once("error", onerr);
            this.once("end", onend);
            this.once("data", ondata);
          });
        };
        return {
          next,
          throw: stop,
          return: stop,
          [Symbol.asyncIterator]() {
            return this;
          }
        };
      }
      /**
       * Synchronous `for of` iteration.
       *
       * The iteration will terminate when the internal buffer runs out, even
       * if the stream has not yet terminated.
       */
      [Symbol.iterator]() {
        this[DISCARDED] = false;
        let stopped = false;
        const stop = () => {
          this.pause();
          this.off(ERROR, stop);
          this.off(DESTROYED, stop);
          this.off("end", stop);
          stopped = true;
          return { done: true, value: void 0 };
        };
        const next = () => {
          if (stopped)
            return stop();
          const value = this.read();
          return value === null ? stop() : { done: false, value };
        };
        this.once("end", stop);
        this.once(ERROR, stop);
        this.once(DESTROYED, stop);
        return {
          next,
          throw: stop,
          return: stop,
          [Symbol.iterator]() {
            return this;
          }
        };
      }
      /**
       * Destroy a stream, preventing it from being used for any further purpose.
       *
       * If the stream has a `close()` method, then it will be called on
       * destruction.
       *
       * After destruction, any attempt to write data, read data, or emit most
       * events will be ignored.
       *
       * If an error argument is provided, then it will be emitted in an
       * 'error' event.
       */
      destroy(er) {
        if (this[DESTROYED]) {
          if (er)
            this.emit("error", er);
          else
            this.emit(DESTROYED);
          return this;
        }
        this[DESTROYED] = true;
        this[DISCARDED] = true;
        this[BUFFER].length = 0;
        this[BUFFERLENGTH] = 0;
        const wc = this;
        if (typeof wc.close === "function" && !this[CLOSED])
          wc.close();
        if (er)
          this.emit("error", er);
        else
          this.emit(DESTROYED);
        return this;
      }
      /**
       * Alias for {@link isStream}
       *
       * Former export location, maintained for backwards compatibility.
       *
       * @deprecated
       */
      static get isStream() {
        return exports2.isStream;
      }
    };
    exports2.Minipass = Minipass;
  }
});

// ../node_modules/.pnpm/ssri@10.0.5/node_modules/ssri/lib/index.js
var require_lib2 = __commonJS({
  "../node_modules/.pnpm/ssri@10.0.5/node_modules/ssri/lib/index.js"(exports2, module2) {
    "use strict";
    var crypto = require("crypto");
    var { Minipass } = require_commonjs();
    var SPEC_ALGORITHMS = ["sha512", "sha384", "sha256"];
    var DEFAULT_ALGORITHMS = ["sha512"];
    var BASE64_REGEX = /^[a-z0-9+/]+(?:=?=?)$/i;
    var SRI_REGEX = /^([a-z0-9]+)-([^?]+)([?\S*]*)$/;
    var STRICT_SRI_REGEX = /^([a-z0-9]+)-([A-Za-z0-9+/=]{44,88})(\?[\x21-\x7E]*)?$/;
    var VCHAR_REGEX = /^[\x21-\x7E]+$/;
    var getOptString = (options) => options?.length ? `?${options.join("?")}` : "";
    var IntegrityStream = class extends Minipass {
      #emittedIntegrity;
      #emittedSize;
      #emittedVerified;
      constructor(opts) {
        super();
        this.size = 0;
        this.opts = opts;
        this.#getOptions();
        if (opts?.algorithms) {
          this.algorithms = [...opts.algorithms];
        } else {
          this.algorithms = [...DEFAULT_ALGORITHMS];
        }
        if (this.algorithm !== null && !this.algorithms.includes(this.algorithm)) {
          this.algorithms.push(this.algorithm);
        }
        this.hashes = this.algorithms.map(crypto.createHash);
      }
      #getOptions() {
        this.sri = this.opts?.integrity ? parse(this.opts?.integrity, this.opts) : null;
        this.expectedSize = this.opts?.size;
        if (!this.sri) {
          this.algorithm = null;
        } else if (this.sri.isHash) {
          this.goodSri = true;
          this.algorithm = this.sri.algorithm;
        } else {
          this.goodSri = !this.sri.isEmpty();
          this.algorithm = this.sri.pickAlgorithm(this.opts);
        }
        this.digests = this.goodSri ? this.sri[this.algorithm] : null;
        this.optString = getOptString(this.opts?.options);
      }
      on(ev, handler) {
        if (ev === "size" && this.#emittedSize) {
          return handler(this.#emittedSize);
        }
        if (ev === "integrity" && this.#emittedIntegrity) {
          return handler(this.#emittedIntegrity);
        }
        if (ev === "verified" && this.#emittedVerified) {
          return handler(this.#emittedVerified);
        }
        return super.on(ev, handler);
      }
      emit(ev, data) {
        if (ev === "end") {
          this.#onEnd();
        }
        return super.emit(ev, data);
      }
      write(data) {
        this.size += data.length;
        this.hashes.forEach((h) => h.update(data));
        return super.write(data);
      }
      #onEnd() {
        if (!this.goodSri) {
          this.#getOptions();
        }
        const newSri = parse(this.hashes.map((h, i) => {
          return `${this.algorithms[i]}-${h.digest("base64")}${this.optString}`;
        }).join(" "), this.opts);
        const match = this.goodSri && newSri.match(this.sri, this.opts);
        if (typeof this.expectedSize === "number" && this.size !== this.expectedSize) {
          const err = new Error(`stream size mismatch when checking ${this.sri}.
  Wanted: ${this.expectedSize}
  Found: ${this.size}`);
          err.code = "EBADSIZE";
          err.found = this.size;
          err.expected = this.expectedSize;
          err.sri = this.sri;
          this.emit("error", err);
        } else if (this.sri && !match) {
          const err = new Error(`${this.sri} integrity checksum failed when using ${this.algorithm}: wanted ${this.digests} but got ${newSri}. (${this.size} bytes)`);
          err.code = "EINTEGRITY";
          err.found = newSri;
          err.expected = this.digests;
          err.algorithm = this.algorithm;
          err.sri = this.sri;
          this.emit("error", err);
        } else {
          this.#emittedSize = this.size;
          this.emit("size", this.size);
          this.#emittedIntegrity = newSri;
          this.emit("integrity", newSri);
          if (match) {
            this.#emittedVerified = match;
            this.emit("verified", match);
          }
        }
      }
    };
    var Hash = class {
      get isHash() {
        return true;
      }
      constructor(hash, opts) {
        const strict = opts?.strict;
        this.source = hash.trim();
        this.digest = "";
        this.algorithm = "";
        this.options = [];
        const match = this.source.match(
          strict ? STRICT_SRI_REGEX : SRI_REGEX
        );
        if (!match) {
          return;
        }
        if (strict && !SPEC_ALGORITHMS.includes(match[1])) {
          return;
        }
        this.algorithm = match[1];
        this.digest = match[2];
        const rawOpts = match[3];
        if (rawOpts) {
          this.options = rawOpts.slice(1).split("?");
        }
      }
      hexDigest() {
        return this.digest && Buffer.from(this.digest, "base64").toString("hex");
      }
      toJSON() {
        return this.toString();
      }
      match(integrity, opts) {
        const other = parse(integrity, opts);
        if (!other) {
          return false;
        }
        if (other.isIntegrity) {
          const algo = other.pickAlgorithm(opts, [this.algorithm]);
          if (!algo) {
            return false;
          }
          const foundHash = other[algo].find((hash) => hash.digest === this.digest);
          if (foundHash) {
            return foundHash;
          }
          return false;
        }
        return other.digest === this.digest ? other : false;
      }
      toString(opts) {
        if (opts?.strict) {
          if (!// The spec has very restricted productions for algorithms.
          // https://www.w3.org/TR/CSP2/#source-list-syntax
          (SPEC_ALGORITHMS.includes(this.algorithm) && // Usually, if someone insists on using a "different" base64, we
          // leave it as-is, since there's multiple standards, and the
          // specified is not a URL-safe variant.
          // https://www.w3.org/TR/CSP2/#base64_value
          this.digest.match(BASE64_REGEX) && // Option syntax is strictly visual chars.
          // https://w3c.github.io/webappsec-subresource-integrity/#grammardef-option-expression
          // https://tools.ietf.org/html/rfc5234#appendix-B.1
          this.options.every((opt) => opt.match(VCHAR_REGEX)))) {
            return "";
          }
        }
        return `${this.algorithm}-${this.digest}${getOptString(this.options)}`;
      }
    };
    function integrityHashToString(toString, sep, opts, hashes) {
      const toStringIsNotEmpty = toString !== "";
      let shouldAddFirstSep = false;
      let complement = "";
      const lastIndex = hashes.length - 1;
      for (let i = 0; i < lastIndex; i++) {
        const hashString = Hash.prototype.toString.call(hashes[i], opts);
        if (hashString) {
          shouldAddFirstSep = true;
          complement += hashString;
          complement += sep;
        }
      }
      const finalHashString = Hash.prototype.toString.call(hashes[lastIndex], opts);
      if (finalHashString) {
        shouldAddFirstSep = true;
        complement += finalHashString;
      }
      if (toStringIsNotEmpty && shouldAddFirstSep) {
        return toString + sep + complement;
      }
      return toString + complement;
    }
    var Integrity = class {
      get isIntegrity() {
        return true;
      }
      toJSON() {
        return this.toString();
      }
      isEmpty() {
        return Object.keys(this).length === 0;
      }
      toString(opts) {
        let sep = opts?.sep || " ";
        let toString = "";
        if (opts?.strict) {
          sep = sep.replace(/\S+/g, " ");
          for (const hash of SPEC_ALGORITHMS) {
            if (this[hash]) {
              toString = integrityHashToString(toString, sep, opts, this[hash]);
            }
          }
        } else {
          for (const hash of Object.keys(this)) {
            toString = integrityHashToString(toString, sep, opts, this[hash]);
          }
        }
        return toString;
      }
      concat(integrity, opts) {
        const other = typeof integrity === "string" ? integrity : stringify(integrity, opts);
        return parse(`${this.toString(opts)} ${other}`, opts);
      }
      hexDigest() {
        return parse(this, { single: true }).hexDigest();
      }
      // add additional hashes to an integrity value, but prevent
      // *changing* an existing integrity hash.
      merge(integrity, opts) {
        const other = parse(integrity, opts);
        for (const algo in other) {
          if (this[algo]) {
            if (!this[algo].find((hash) => other[algo].find((otherhash) => hash.digest === otherhash.digest))) {
              throw new Error("hashes do not match, cannot update integrity");
            }
          } else {
            this[algo] = other[algo];
          }
        }
      }
      match(integrity, opts) {
        const other = parse(integrity, opts);
        if (!other) {
          return false;
        }
        const algo = other.pickAlgorithm(opts, Object.keys(this));
        return !!algo && this[algo] && other[algo] && this[algo].find(
          (hash) => other[algo].find(
            (otherhash) => hash.digest === otherhash.digest
          )
        ) || false;
      }
      // Pick the highest priority algorithm present, optionally also limited to a
      // set of hashes found in another integrity.  When limiting it may return
      // nothing.
      pickAlgorithm(opts, hashes) {
        const pickAlgorithm = opts?.pickAlgorithm || getPrioritizedHash;
        const keys = Object.keys(this).filter((k) => {
          if (hashes?.length) {
            return hashes.includes(k);
          }
          return true;
        });
        if (keys.length) {
          return keys.reduce((acc, algo) => pickAlgorithm(acc, algo) || acc);
        }
        return null;
      }
    };
    module2.exports.parse = parse;
    function parse(sri, opts) {
      if (!sri) {
        return null;
      }
      if (typeof sri === "string") {
        return _parse(sri, opts);
      } else if (sri.algorithm && sri.digest) {
        const fullSri = new Integrity();
        fullSri[sri.algorithm] = [sri];
        return _parse(stringify(fullSri, opts), opts);
      } else {
        return _parse(stringify(sri, opts), opts);
      }
    }
    function _parse(integrity, opts) {
      if (opts?.single) {
        return new Hash(integrity, opts);
      }
      const hashes = integrity.trim().split(/\s+/).reduce((acc, string) => {
        const hash = new Hash(string, opts);
        if (hash.algorithm && hash.digest) {
          const algo = hash.algorithm;
          if (!acc[algo]) {
            acc[algo] = [];
          }
          acc[algo].push(hash);
        }
        return acc;
      }, new Integrity());
      return hashes.isEmpty() ? null : hashes;
    }
    module2.exports.stringify = stringify;
    function stringify(obj, opts) {
      if (obj.algorithm && obj.digest) {
        return Hash.prototype.toString.call(obj, opts);
      } else if (typeof obj === "string") {
        return stringify(parse(obj, opts), opts);
      } else {
        return Integrity.prototype.toString.call(obj, opts);
      }
    }
    module2.exports.fromHex = fromHex;
    function fromHex(hexDigest, algorithm, opts) {
      const optString = getOptString(opts?.options);
      return parse(
        `${algorithm}-${Buffer.from(hexDigest, "hex").toString("base64")}${optString}`,
        opts
      );
    }
    module2.exports.fromData = fromData;
    function fromData(data, opts) {
      const algorithms = opts?.algorithms || [...DEFAULT_ALGORITHMS];
      const optString = getOptString(opts?.options);
      return algorithms.reduce((acc, algo) => {
        const digest = crypto.createHash(algo).update(data).digest("base64");
        const hash = new Hash(
          `${algo}-${digest}${optString}`,
          opts
        );
        if (hash.algorithm && hash.digest) {
          const hashAlgo = hash.algorithm;
          if (!acc[hashAlgo]) {
            acc[hashAlgo] = [];
          }
          acc[hashAlgo].push(hash);
        }
        return acc;
      }, new Integrity());
    }
    module2.exports.fromStream = fromStream;
    function fromStream(stream, opts) {
      const istream = integrityStream(opts);
      return new Promise((resolve, reject) => {
        stream.pipe(istream);
        stream.on("error", reject);
        istream.on("error", reject);
        let sri;
        istream.on("integrity", (s) => {
          sri = s;
        });
        istream.on("end", () => resolve(sri));
        istream.resume();
      });
    }
    module2.exports.checkData = checkData;
    function checkData(data, sri, opts) {
      sri = parse(sri, opts);
      if (!sri || !Object.keys(sri).length) {
        if (opts?.error) {
          throw Object.assign(
            new Error("No valid integrity hashes to check against"),
            {
              code: "EINTEGRITY"
            }
          );
        } else {
          return false;
        }
      }
      const algorithm = sri.pickAlgorithm(opts);
      const digest = crypto.createHash(algorithm).update(data).digest("base64");
      const newSri = parse({ algorithm, digest });
      const match = newSri.match(sri, opts);
      opts = opts || {};
      if (match || !opts.error) {
        return match;
      } else if (typeof opts.size === "number" && data.length !== opts.size) {
        const err = new Error(`data size mismatch when checking ${sri}.
  Wanted: ${opts.size}
  Found: ${data.length}`);
        err.code = "EBADSIZE";
        err.found = data.length;
        err.expected = opts.size;
        err.sri = sri;
        throw err;
      } else {
        const err = new Error(`Integrity checksum failed when using ${algorithm}: Wanted ${sri}, but got ${newSri}. (${data.length} bytes)`);
        err.code = "EINTEGRITY";
        err.found = newSri;
        err.expected = sri;
        err.algorithm = algorithm;
        err.sri = sri;
        throw err;
      }
    }
    module2.exports.checkStream = checkStream;
    function checkStream(stream, sri, opts) {
      opts = opts || /* @__PURE__ */ Object.create(null);
      opts.integrity = sri;
      sri = parse(sri, opts);
      if (!sri || !Object.keys(sri).length) {
        return Promise.reject(Object.assign(
          new Error("No valid integrity hashes to check against"),
          {
            code: "EINTEGRITY"
          }
        ));
      }
      const checker = integrityStream(opts);
      return new Promise((resolve, reject) => {
        stream.pipe(checker);
        stream.on("error", reject);
        checker.on("error", reject);
        let verified;
        checker.on("verified", (s) => {
          verified = s;
        });
        checker.on("end", () => resolve(verified));
        checker.resume();
      });
    }
    module2.exports.integrityStream = integrityStream;
    function integrityStream(opts = /* @__PURE__ */ Object.create(null)) {
      return new IntegrityStream(opts);
    }
    module2.exports.create = createIntegrity;
    function createIntegrity(opts) {
      const algorithms = opts?.algorithms || [...DEFAULT_ALGORITHMS];
      const optString = getOptString(opts?.options);
      const hashes = algorithms.map(crypto.createHash);
      return {
        update: function(chunk, enc) {
          hashes.forEach((h) => h.update(chunk, enc));
          return this;
        },
        digest: function(enc) {
          const integrity = algorithms.reduce((acc, algo) => {
            const digest = hashes.shift().digest("base64");
            const hash = new Hash(
              `${algo}-${digest}${optString}`,
              opts
            );
            if (hash.algorithm && hash.digest) {
              const hashAlgo = hash.algorithm;
              if (!acc[hashAlgo]) {
                acc[hashAlgo] = [];
              }
              acc[hashAlgo].push(hash);
            }
            return acc;
          }, new Integrity());
          return integrity;
        }
      };
    }
    var NODE_HASHES = crypto.getHashes();
    var DEFAULT_PRIORITY = [
      "md5",
      "whirlpool",
      "sha1",
      "sha224",
      "sha256",
      "sha384",
      "sha512",
      // TODO - it's unclear _which_ of these Node will actually use as its name
      //        for the algorithm, so we guesswork it based on the OpenSSL names.
      "sha3",
      "sha3-256",
      "sha3-384",
      "sha3-512",
      "sha3_256",
      "sha3_384",
      "sha3_512"
    ].filter((algo) => NODE_HASHES.includes(algo));
    function getPrioritizedHash(algo1, algo2) {
      return DEFAULT_PRIORITY.indexOf(algo1.toLowerCase()) >= DEFAULT_PRIORITY.indexOf(algo2.toLowerCase()) ? algo1 : algo2;
    }
  }
});

// ../node_modules/.pnpm/is-windows@1.0.2/node_modules/is-windows/index.js
var require_is_windows = __commonJS({
  "../node_modules/.pnpm/is-windows@1.0.2/node_modules/is-windows/index.js"(exports2, module2) {
    (function(factory) {
      if (exports2 && typeof exports2 === "object" && typeof module2 !== "undefined") {
        module2.exports = factory();
      } else if (typeof define === "function" && define.amd) {
        define([], factory);
      } else if (typeof window !== "undefined") {
        window.isWindows = factory();
      } else if (typeof global !== "undefined") {
        global.isWindows = factory();
      } else if (typeof self !== "undefined") {
        self.isWindows = factory();
      } else {
        this.isWindows = factory();
      }
    })(function() {
      "use strict";
      return function isWindows() {
        return process && (process.platform === "win32" || /^(msys|cygwin)$/.test(process.env.OSTYPE));
      };
    });
  }
});

// ../node_modules/.pnpm/better-path-resolve@1.0.0/node_modules/better-path-resolve/index.js
var require_better_path_resolve = __commonJS({
  "../node_modules/.pnpm/better-path-resolve@1.0.0/node_modules/better-path-resolve/index.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    var isWindows = require_is_windows();
    module2.exports = isWindows() ? winResolve : path.resolve;
    function winResolve(p) {
      if (arguments.length === 0) return path.resolve();
      if (typeof p !== "string") {
        return path.resolve(p);
      }
      if (p[1] === ":") {
        const cc = p[0].charCodeAt();
        if (cc < 65 || cc > 90) {
          p = `${p[0].toUpperCase()}${p.substr(1)}`;
        }
      }
      if (p.endsWith(":")) {
        return p;
      }
      return path.resolve(p);
    }
  }
});

// ../node_modules/.pnpm/is-subdir@1.2.0/node_modules/is-subdir/index.js
var require_is_subdir = __commonJS({
  "../node_modules/.pnpm/is-subdir@1.2.0/node_modules/is-subdir/index.js"(exports2, module2) {
    "use strict";
    var betterPathResolve = require_better_path_resolve();
    var path = require("path");
    function isSubdir(parentDir, subdir) {
      const rParent = `${betterPathResolve(parentDir)}${path.sep}`;
      const rDir = `${betterPathResolve(subdir)}${path.sep}`;
      return rDir.startsWith(rParent);
    }
    isSubdir.strict = function isSubdirStrict(parentDir, subdir) {
      const rParent = `${betterPathResolve(parentDir)}${path.sep}`;
      const rDir = `${betterPathResolve(subdir)}${path.sep}`;
      return rDir !== rParent && rDir.startsWith(rParent);
    };
    module2.exports = isSubdir;
  }
});

// ../node_modules/.pnpm/strip-bom@4.0.0/node_modules/strip-bom/index.js
var require_strip_bom = __commonJS({
  "../node_modules/.pnpm/strip-bom@4.0.0/node_modules/strip-bom/index.js"(exports2, module2) {
    "use strict";
    module2.exports = (string) => {
      if (typeof string !== "string") {
        throw new TypeError(`Expected a string, got ${typeof string}`);
      }
      if (string.charCodeAt(0) === 65279) {
        return string.slice(1);
      }
      return string;
    };
  }
});

// ../store/cafs/lib/parseJson.js
var require_parseJson = __commonJS({
  "../store/cafs/lib/parseJson.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.parseJsonBufferSync = parseJsonBufferSync;
    var strip_bom_1 = __importDefault(require_strip_bom());
    function parseJsonBufferSync(buffer) {
      return JSON.parse((0, strip_bom_1.default)(buffer.toString()));
    }
  }
});

// ../store/cafs/lib/addFilesFromDir.js
var require_addFilesFromDir = __commonJS({
  "../store/cafs/lib/addFilesFromDir.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.addFilesFromDir = addFilesFromDir;
    var util_1 = __importDefault(require("util"));
    var fs_1 = __importDefault(require("fs"));
    var path_1 = __importDefault(require("path"));
    var graceful_fs_1 = __importDefault(require_lib());
    var is_subdir_1 = __importDefault(require_is_subdir());
    var parseJson_js_1 = require_parseJson();
    function addFilesFromDir(addBuffer, dirname, opts = {}) {
      const filesIndex = {};
      let manifest;
      let files;
      const resolvedRoot = fs_1.default.realpathSync(dirname);
      if (opts.files) {
        files = [];
        for (const file of opts.files) {
          const absolutePath = path_1.default.join(dirname, file);
          const stat = getStatIfContained(absolutePath, resolvedRoot);
          if (!stat) {
            continue;
          }
          files.push({
            absolutePath,
            relativePath: file,
            stat
          });
        }
      } else {
        files = findFilesInDir(dirname, resolvedRoot);
      }
      for (const { absolutePath, relativePath, stat } of files) {
        const buffer = graceful_fs_1.default.readFileSync(absolutePath);
        if (opts.readManifest && relativePath === "package.json") {
          manifest = (0, parseJson_js_1.parseJsonBufferSync)(buffer);
        }
        const mode = stat.mode & 511;
        filesIndex[relativePath] = {
          mode,
          size: stat.size,
          ...addBuffer(buffer, mode)
        };
      }
      return { manifest, filesIndex };
    }
    function getStatIfContained(absolutePath, rootDir) {
      let lstat;
      try {
        lstat = fs_1.default.lstatSync(absolutePath);
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") {
          return null;
        }
        throw err;
      }
      if (lstat.isSymbolicLink()) {
        return getSymlinkStatIfContained(absolutePath, rootDir)?.stat ?? null;
      }
      return lstat;
    }
    function getSymlinkStatIfContained(absolutePath, rootDir) {
      let realPath;
      try {
        realPath = fs_1.default.realpathSync(absolutePath);
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") {
          return null;
        }
        throw err;
      }
      if (!(0, is_subdir_1.default)(rootDir, realPath)) {
        return null;
      }
      return { stat: fs_1.default.statSync(realPath), realPath };
    }
    function findFilesInDir(dir, rootDir) {
      const files = [];
      const ctx = {
        filesList: files,
        rootDir,
        visited: /* @__PURE__ */ new Set([rootDir])
      };
      findFiles(ctx, dir, "", rootDir);
      return files;
    }
    function findFiles(ctx, dir, relativeDir, currentRealPath) {
      const files = fs_1.default.readdirSync(dir, { withFileTypes: true });
      for (const file of files) {
        const relativeSubdir = `${relativeDir}${relativeDir ? "/" : ""}${file.name}`;
        const absolutePath = path_1.default.join(dir, file.name);
        let nextRealDir;
        if (file.isSymbolicLink()) {
          const res = getSymlinkStatIfContained(absolutePath, ctx.rootDir);
          if (!res) {
            continue;
          }
          if (res.stat.isDirectory()) {
            nextRealDir = res.realPath;
          } else {
            ctx.filesList.push({
              relativePath: relativeSubdir,
              absolutePath,
              stat: res.stat
            });
            continue;
          }
        } else if (file.isDirectory()) {
          nextRealDir = path_1.default.join(currentRealPath, file.name);
        }
        if (nextRealDir) {
          if (ctx.visited.has(nextRealDir))
            continue;
          if (relativeDir !== "" || file.name !== "node_modules") {
            ctx.visited.add(nextRealDir);
            findFiles(ctx, absolutePath, relativeSubdir, nextRealDir);
            ctx.visited.delete(nextRealDir);
          }
          continue;
        }
        let stat;
        try {
          stat = fs_1.default.statSync(absolutePath);
        } catch (err) {
          if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") {
            continue;
          }
          throw err;
        }
        ctx.filesList.push({
          relativePath: relativeSubdir,
          absolutePath,
          stat
        });
      }
    }
  }
});

// ../node_modules/.pnpm/is-gzip@2.0.0/node_modules/is-gzip/index.js
var require_is_gzip = __commonJS({
  "../node_modules/.pnpm/is-gzip@2.0.0/node_modules/is-gzip/index.js"(exports2, module2) {
    "use strict";
    module2.exports = (buf) => {
      if (!buf || buf.length < 3) {
        return false;
      }
      return buf[0] === 31 && buf[1] === 139 && buf[2] === 8;
    };
  }
});

// ../store/cafs/lib/parseTarball.js
var require_parseTarball = __commonJS({
  "../store/cafs/lib/parseTarball.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.parseTarball = parseTarball;
    var path_1 = __importDefault(require("path"));
    var ZERO = "0".charCodeAt(0);
    var FILE_TYPE_HARD_LINK = "1".charCodeAt(0);
    var FILE_TYPE_SYMLINK = "2".charCodeAt(0);
    var FILE_TYPE_DIRECTORY = "5".charCodeAt(0);
    var SPACE = " ".charCodeAt(0);
    var SLASH = "/".charCodeAt(0);
    var BACKSLASH = "\\".charCodeAt(0);
    var FILE_TYPE_PAX_HEADER = "x".charCodeAt(0);
    var FILE_TYPE_PAX_GLOBAL_HEADER = "g".charCodeAt(0);
    var FILE_TYPE_LONGLINK = "L".charCodeAt(0);
    var MODE_OFFSET = 100;
    var FILE_SIZE_OFFSET = 124;
    var CHECKSUM_OFFSET = 148;
    var FILE_TYPE_OFFSET = 156;
    var PREFIX_OFFSET = 345;
    function parseTarball(buffer) {
      const files = /* @__PURE__ */ new Map();
      let pathTrimmed = false;
      let mode = 0;
      let fileSize = 0;
      let fileType = 0;
      let prefix = "";
      let fileName = "";
      let longLinkPath = "";
      let paxHeaderPath = "";
      let paxHeaderFileSize;
      let blockBytes = 0;
      let blockStart = 0;
      while (buffer[blockStart] !== 0) {
        fileType = buffer[blockStart + FILE_TYPE_OFFSET];
        if (paxHeaderFileSize !== void 0) {
          fileSize = paxHeaderFileSize;
          paxHeaderFileSize = void 0;
        } else {
          fileSize = parseOctal(blockStart + FILE_SIZE_OFFSET, 12);
        }
        blockBytes = (fileSize & ~511) + (fileSize & 511 ? 1024 : 512);
        const expectedCheckSum = parseOctal(blockStart + CHECKSUM_OFFSET, 8);
        const actualCheckSum = checkSum(blockStart);
        if (expectedCheckSum !== actualCheckSum) {
          throw new Error(`Invalid checksum for TAR header at offset ${blockStart}. Expected ${expectedCheckSum}, got ${actualCheckSum}`);
        }
        pathTrimmed = false;
        if (longLinkPath) {
          fileName = longLinkPath;
          longLinkPath = "";
        } else if (paxHeaderPath) {
          fileName = paxHeaderPath;
          paxHeaderPath = "";
        } else {
          prefix = parseString(blockStart + PREFIX_OFFSET, 155);
          if (prefix && !pathTrimmed) {
            pathTrimmed = true;
            prefix = "";
          }
          fileName = parseString(blockStart, MODE_OFFSET);
          if (prefix) {
            fileName = `${prefix}/${fileName}`;
          }
        }
        if (fileName.includes("./") || fileName.includes(".\\")) {
          fileName = path_1.default.posix.join("/", fileName.replaceAll("\\", "/")).slice(1);
        }
        switch (fileType) {
          case 0:
          case ZERO:
          case FILE_TYPE_HARD_LINK:
            mode = parseOctal(blockStart + MODE_OFFSET, 8);
            files.set(fileName.replaceAll("//", "/"), { offset: blockStart + 512, mode, size: fileSize });
            break;
          case FILE_TYPE_DIRECTORY:
          case FILE_TYPE_SYMLINK:
            break;
          case FILE_TYPE_PAX_HEADER:
            parsePaxHeader(blockStart + 512, fileSize, false);
            break;
          case FILE_TYPE_PAX_GLOBAL_HEADER:
            parsePaxHeader(blockStart + 512, fileSize, true);
            break;
          case FILE_TYPE_LONGLINK: {
            longLinkPath = buffer.toString("utf8", blockStart + 512, blockStart + 512 + fileSize).replace(/\0.*/, "");
            const slashIndex = longLinkPath.indexOf("/");
            if (slashIndex >= 0) {
              longLinkPath = longLinkPath.slice(slashIndex + 1);
            }
            break;
          }
          default:
            throw new Error(`Unsupported file type ${fileType} for file ${fileName}.`);
        }
        blockStart += blockBytes;
      }
      return { files, buffer: buffer.buffer };
      function checkSum(offset) {
        let sum = 256;
        let i = offset;
        const checksumStart = offset + 148;
        const checksumEnd = offset + 156;
        const blockEnd = offset + 512;
        for (; i < checksumStart; i++) {
          sum += buffer[i];
        }
        for (i = checksumEnd; i < blockEnd; i++) {
          sum += buffer[i];
        }
        return sum;
      }
      function parsePaxHeader(offset, length, global2) {
        const end = offset + length;
        let i = offset;
        while (i < end) {
          const lineStart = i;
          while (i < end && buffer[i] !== SPACE) {
            i++;
          }
          const strLen = buffer.toString("utf-8", lineStart, i);
          const len = parseInt(strLen, 10);
          if (!len) {
            throw new Error(`Invalid length in PAX record: ${strLen}`);
          }
          i++;
          const lineEnd = lineStart + len;
          const record = buffer.toString("utf-8", i, lineEnd - 1);
          i = lineEnd;
          const equalSign = record.indexOf("=");
          const keyword = record.slice(0, equalSign);
          if (keyword === "path") {
            const slashIndex = record.indexOf("/", equalSign + 1);
            if (global2) {
              throw new Error(`Unexpected global PAX path: ${record}`);
            }
            paxHeaderPath = record.slice(slashIndex >= 0 ? slashIndex + 1 : equalSign + 1);
          } else if (keyword === "size") {
            const size = parseInt(record.slice(equalSign + 1), 10);
            if (isNaN(size) || size < 0) {
              throw new Error(`Invalid size in PAX record: ${record}`);
            }
            if (global2) {
              throw new Error(`Unexpected global PAX file size: ${record}`);
            }
            paxHeaderFileSize = size;
          } else {
            continue;
          }
        }
      }
      function parseString(offset, length) {
        let end = offset;
        const max = length + offset;
        for (let char = buffer[end]; char !== 0 && end !== max; char = buffer[++end]) {
          if (!pathTrimmed && (char === SLASH || char === BACKSLASH)) {
            pathTrimmed = true;
            offset = end + 1;
          }
        }
        return buffer.toString("utf8", offset, end);
      }
      function parseOctal(offset, length) {
        const val = buffer.subarray(offset, offset + length);
        offset = 0;
        while (offset < val.length && val[offset] === SPACE)
          offset++;
        const end = clamp(indexOf(val, SPACE, offset, val.length), val.length, val.length);
        while (offset < end && val[offset] === 0)
          offset++;
        if (end === offset)
          return 0;
        return parseInt(val.slice(offset, end).toString(), 8);
      }
    }
    function indexOf(block, num, offset, end) {
      for (; offset < end; offset++) {
        if (block[offset] === num)
          return offset;
      }
      return end;
    }
    function clamp(index, len, defaultValue) {
      if (typeof index !== "number")
        return defaultValue;
      index = ~~index;
      if (index >= len)
        return len;
      if (index >= 0)
        return index;
      index += len;
      if (index >= 0)
        return index;
      return 0;
    }
  }
});

// ../store/cafs/lib/addFilesFromTarball.js
var require_addFilesFromTarball = __commonJS({
  "../store/cafs/lib/addFilesFromTarball.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.addFilesFromTarball = addFilesFromTarball;
    var is_gzip_1 = __importDefault(require_is_gzip());
    var zlib_1 = require("zlib");
    var parseJson_js_1 = require_parseJson();
    var parseTarball_js_1 = require_parseTarball();
    function addFilesFromTarball(addBufferToCafs, _ignore, tarballBuffer, readManifest) {
      const ignore = _ignore ?? (() => false);
      const tarContent = (0, is_gzip_1.default)(tarballBuffer) ? (0, zlib_1.gunzipSync)(tarballBuffer) : Buffer.isBuffer(tarballBuffer) ? tarballBuffer : Buffer.from(tarballBuffer);
      const { files } = (0, parseTarball_js_1.parseTarball)(tarContent);
      const filesIndex = {};
      let manifestBuffer;
      for (const [relativePath, { mode, offset, size }] of files) {
        if (ignore(relativePath))
          continue;
        const fileBuffer = tarContent.subarray(offset, offset + size);
        if (readManifest && relativePath === "package.json") {
          manifestBuffer = fileBuffer;
        }
        filesIndex[relativePath] = {
          mode,
          size,
          ...addBufferToCafs(fileBuffer, mode)
        };
      }
      return {
        filesIndex,
        manifest: manifestBuffer ? (0, parseJson_js_1.parseJsonBufferSync)(manifestBuffer) : void 0
      };
    }
  }
});

// ../node_modules/.pnpm/@zkochan+rimraf@3.0.2/node_modules/@zkochan/rimraf/index.js
var require_rimraf = __commonJS({
  "../node_modules/.pnpm/@zkochan+rimraf@3.0.2/node_modules/@zkochan/rimraf/index.js"(exports2, module2) {
    var fs = require("fs");
    module2.exports = async (p) => {
      try {
        await fs.promises.rm(p, { recursive: true, force: true, maxRetries: 3 });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
    };
    module2.exports.sync = (p) => {
      try {
        fs.rmSync(p, { recursive: true, force: true, maxRetries: 3 });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
    };
  }
});

// ../store/cafs/lib/getFilePathInCafs.js
var require_getFilePathInCafs = __commonJS({
  "../store/cafs/lib/getFilePathInCafs.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.modeIsExecutable = void 0;
    exports2.getFilePathByModeInCafs = getFilePathByModeInCafs;
    exports2.getIndexFilePathInCafs = getIndexFilePathInCafs;
    exports2.contentPathFromHex = contentPathFromHex;
    var path_1 = __importDefault(require("path"));
    var ssri_1 = __importDefault(require_lib2());
    var modeIsExecutable = (mode) => (mode & 73) !== 0;
    exports2.modeIsExecutable = modeIsExecutable;
    function getFilePathByModeInCafs(storeDir, integrity, mode) {
      const fileType = (0, exports2.modeIsExecutable)(mode) ? "exec" : "nonexec";
      return path_1.default.join(storeDir, contentPathFromIntegrity(integrity, fileType));
    }
    function getIndexFilePathInCafs(storeDir, integrity, pkgId) {
      const hex = ssri_1.default.parse(integrity, { single: true }).hexDigest().substring(0, 64);
      return path_1.default.join(storeDir, `index/${path_1.default.join(hex.slice(0, 2), hex.slice(2))}-${pkgId.replace(/[\\/:*?"<>|]/g, "+")}.json`);
    }
    function contentPathFromIntegrity(integrity, fileType) {
      const sri = ssri_1.default.parse(integrity, { single: true });
      return contentPathFromHex(fileType, sri.hexDigest());
    }
    function contentPathFromHex(fileType, hex) {
      const p = path_1.default.join("files", hex.slice(0, 2), hex.slice(2));
      switch (fileType) {
        case "exec":
          return `${p}-exec`;
        case "nonexec":
          return p;
        case "index":
          return `${p}-index.json`;
      }
    }
  }
});

// ../store/cafs/lib/checkPkgFilesIntegrity.js
var require_checkPkgFilesIntegrity = __commonJS({
  "../store/cafs/lib/checkPkgFilesIntegrity.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.checkPkgFilesIntegrity = checkPkgFilesIntegrity;
    exports2.verifyFileIntegrity = verifyFileIntegrity;
    var fs_1 = __importDefault(require("fs"));
    var util_1 = __importDefault(require("util"));
    var graceful_fs_1 = __importDefault(require_lib());
    var rimraf_1 = __importDefault(require_rimraf());
    var ssri_1 = __importDefault(require_lib2());
    var getFilePathInCafs_js_1 = require_getFilePathInCafs();
    var parseJson_js_1 = require_parseJson();
    global["verifiedFileIntegrity"] = 0;
    function checkPkgFilesIntegrity(storeDir, pkgIndex, readManifest) {
      const verifiedFilesCache = /* @__PURE__ */ new Set();
      const _checkFilesIntegrity = checkFilesIntegrity.bind(null, verifiedFilesCache, storeDir);
      const verified = _checkFilesIntegrity(pkgIndex.files, readManifest);
      if (!verified)
        return { passed: false };
      if (pkgIndex.sideEffects) {
        for (const [sideEffectName, { added }] of Object.entries(pkgIndex.sideEffects)) {
          if (added) {
            const { passed } = _checkFilesIntegrity(added);
            if (!passed) {
              delete pkgIndex.sideEffects[sideEffectName];
            }
          }
        }
      }
      return verified;
    }
    function checkFilesIntegrity(verifiedFilesCache, storeDir, files, readManifest) {
      let allVerified = true;
      let manifest;
      for (const [f, fstat] of Object.entries(files)) {
        if (!fstat.integrity) {
          throw new Error(`Integrity checksum is missing for ${f}`);
        }
        const filename = (0, getFilePathInCafs_js_1.getFilePathByModeInCafs)(storeDir, fstat.integrity, fstat.mode);
        const readFile = readManifest && f === "package.json";
        if (!readFile && verifiedFilesCache.has(filename))
          continue;
        const verifyResult = verifyFile(filename, fstat, readFile);
        if (readFile) {
          manifest = verifyResult.manifest;
        }
        if (verifyResult.passed) {
          verifiedFilesCache.add(filename);
        } else {
          allVerified = false;
        }
      }
      return {
        passed: allVerified,
        manifest
      };
    }
    function verifyFile(filename, fstat, readManifest) {
      const currentFile = checkFile(filename, fstat.checkedAt);
      if (currentFile == null)
        return { passed: false };
      if (currentFile.isModified) {
        if (currentFile.size !== fstat.size) {
          rimraf_1.default.sync(filename);
          return { passed: false };
        }
        return verifyFileIntegrity(filename, fstat, readManifest);
      }
      if (readManifest) {
        return {
          passed: true,
          manifest: (0, parseJson_js_1.parseJsonBufferSync)(graceful_fs_1.default.readFileSync(filename))
        };
      }
      return { passed: true };
    }
    function verifyFileIntegrity(filename, expectedFile, readManifest) {
      global["verifiedFileIntegrity"]++;
      try {
        const data = graceful_fs_1.default.readFileSync(filename);
        const passed = Boolean(ssri_1.default.checkData(data, expectedFile.integrity));
        if (!passed) {
          graceful_fs_1.default.unlinkSync(filename);
          return { passed };
        } else if (readManifest) {
          return {
            passed,
            manifest: (0, parseJson_js_1.parseJsonBufferSync)(data)
          };
        }
        return { passed };
      } catch (err) {
        switch (util_1.default.types.isNativeError(err) && "code" in err && err.code) {
          case "ENOENT":
            return { passed: false };
          case "EINTEGRITY": {
            graceful_fs_1.default.unlinkSync(filename);
            return { passed: false };
          }
        }
        throw err;
      }
    }
    function checkFile(filename, checkedAt) {
      try {
        const { mtimeMs, size } = fs_1.default.statSync(filename);
        return {
          isModified: mtimeMs - (checkedAt ?? 0) > 100,
          size
        };
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT")
          return null;
        throw err;
      }
    }
  }
});

// ../store/cafs/lib/readManifestFromStore.js
var require_readManifestFromStore = __commonJS({
  "../store/cafs/lib/readManifestFromStore.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.readManifestFromStore = readManifestFromStore;
    var graceful_fs_1 = __importDefault(require_lib());
    var getFilePathInCafs_js_1 = require_getFilePathInCafs();
    var parseJson_js_1 = require_parseJson();
    function readManifestFromStore(storeDir, pkgIndex) {
      const pkg = pkgIndex.files["package.json"];
      if (pkg) {
        const fileName = (0, getFilePathInCafs_js_1.getFilePathByModeInCafs)(storeDir, pkg.integrity, pkg.mode);
        return (0, parseJson_js_1.parseJsonBufferSync)(graceful_fs_1.default.readFileSync(fileName));
      }
      return void 0;
    }
  }
});

// ../node_modules/.pnpm/universalify@2.0.1/node_modules/universalify/index.js
var require_universalify = __commonJS({
  "../node_modules/.pnpm/universalify@2.0.1/node_modules/universalify/index.js"(exports2) {
    "use strict";
    exports2.fromCallback = function(fn) {
      return Object.defineProperty(function(...args) {
        if (typeof args[args.length - 1] === "function") fn.apply(this, args);
        else {
          return new Promise((resolve, reject) => {
            args.push((err, res) => err != null ? reject(err) : resolve(res));
            fn.apply(this, args);
          });
        }
      }, "name", { value: fn.name });
    };
    exports2.fromPromise = function(fn) {
      return Object.defineProperty(function(...args) {
        const cb = args[args.length - 1];
        if (typeof cb !== "function") return fn.apply(this, args);
        else {
          args.pop();
          fn.apply(this, args).then((r) => cb(null, r), cb);
        }
      }, "name", { value: fn.name });
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/fs/index.js
var require_fs = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/fs/index.js"(exports2) {
    "use strict";
    var u = require_universalify().fromCallback;
    var fs = require_graceful_fs();
    var api = [
      "access",
      "appendFile",
      "chmod",
      "chown",
      "close",
      "copyFile",
      "cp",
      "fchmod",
      "fchown",
      "fdatasync",
      "fstat",
      "fsync",
      "ftruncate",
      "futimes",
      "glob",
      "lchmod",
      "lchown",
      "lutimes",
      "link",
      "lstat",
      "mkdir",
      "mkdtemp",
      "open",
      "opendir",
      "readdir",
      "readFile",
      "readlink",
      "realpath",
      "rename",
      "rm",
      "rmdir",
      "stat",
      "statfs",
      "symlink",
      "truncate",
      "unlink",
      "utimes",
      "writeFile"
    ].filter((key) => {
      return typeof fs[key] === "function";
    });
    Object.assign(exports2, fs);
    api.forEach((method) => {
      exports2[method] = u(fs[method]);
    });
    exports2.exists = function(filename, callback) {
      if (typeof callback === "function") {
        return fs.exists(filename, callback);
      }
      return new Promise((resolve) => {
        return fs.exists(filename, resolve);
      });
    };
    exports2.read = function(fd, buffer, offset, length, position, callback) {
      if (typeof callback === "function") {
        return fs.read(fd, buffer, offset, length, position, callback);
      }
      return new Promise((resolve, reject) => {
        fs.read(fd, buffer, offset, length, position, (err, bytesRead, buffer2) => {
          if (err) return reject(err);
          resolve({ bytesRead, buffer: buffer2 });
        });
      });
    };
    exports2.write = function(fd, buffer, ...args) {
      if (typeof args[args.length - 1] === "function") {
        return fs.write(fd, buffer, ...args);
      }
      return new Promise((resolve, reject) => {
        fs.write(fd, buffer, ...args, (err, bytesWritten, buffer2) => {
          if (err) return reject(err);
          resolve({ bytesWritten, buffer: buffer2 });
        });
      });
    };
    exports2.readv = function(fd, buffers, ...args) {
      if (typeof args[args.length - 1] === "function") {
        return fs.readv(fd, buffers, ...args);
      }
      return new Promise((resolve, reject) => {
        fs.readv(fd, buffers, ...args, (err, bytesRead, buffers2) => {
          if (err) return reject(err);
          resolve({ bytesRead, buffers: buffers2 });
        });
      });
    };
    exports2.writev = function(fd, buffers, ...args) {
      if (typeof args[args.length - 1] === "function") {
        return fs.writev(fd, buffers, ...args);
      }
      return new Promise((resolve, reject) => {
        fs.writev(fd, buffers, ...args, (err, bytesWritten, buffers2) => {
          if (err) return reject(err);
          resolve({ bytesWritten, buffers: buffers2 });
        });
      });
    };
    if (typeof fs.realpath.native === "function") {
      exports2.realpath.native = u(fs.realpath.native);
    } else {
      process.emitWarning(
        "fs.realpath.native is not a function. Is fs being monkey-patched?",
        "Warning",
        "fs-extra-WARN0003"
      );
    }
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/mkdirs/utils.js
var require_utils = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/mkdirs/utils.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    module2.exports.checkPath = function checkPath(pth) {
      if (process.platform === "win32") {
        const pathHasInvalidWinCharacters = /[<>:"|?*]/.test(pth.replace(path.parse(pth).root, ""));
        if (pathHasInvalidWinCharacters) {
          const error = new Error(`Path contains invalid characters: ${pth}`);
          error.code = "EINVAL";
          throw error;
        }
      }
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/mkdirs/make-dir.js
var require_make_dir = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/mkdirs/make-dir.js"(exports2, module2) {
    "use strict";
    var fs = require_fs();
    var { checkPath } = require_utils();
    var getMode = (options) => {
      const defaults = { mode: 511 };
      if (typeof options === "number") return options;
      return { ...defaults, ...options }.mode;
    };
    module2.exports.makeDir = async (dir, options) => {
      checkPath(dir);
      return fs.mkdir(dir, {
        mode: getMode(options),
        recursive: true
      });
    };
    module2.exports.makeDirSync = (dir, options) => {
      checkPath(dir);
      return fs.mkdirSync(dir, {
        mode: getMode(options),
        recursive: true
      });
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/mkdirs/index.js
var require_mkdirs = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/mkdirs/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var { makeDir: _makeDir, makeDirSync } = require_make_dir();
    var makeDir = u(_makeDir);
    module2.exports = {
      mkdirs: makeDir,
      mkdirsSync: makeDirSync,
      // alias
      mkdirp: makeDir,
      mkdirpSync: makeDirSync,
      ensureDir: makeDir,
      ensureDirSync: makeDirSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/path-exists/index.js
var require_path_exists = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/path-exists/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var fs = require_fs();
    function pathExists(path) {
      return fs.access(path).then(() => true).catch(() => false);
    }
    module2.exports = {
      pathExists: u(pathExists),
      pathExistsSync: fs.existsSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/util/utimes.js
var require_utimes = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/util/utimes.js"(exports2, module2) {
    "use strict";
    var fs = require_fs();
    var u = require_universalify().fromPromise;
    async function utimesMillis(path, atime, mtime) {
      const fd = await fs.open(path, "r+");
      let closeErr = null;
      try {
        await fs.futimes(fd, atime, mtime);
      } finally {
        try {
          await fs.close(fd);
        } catch (e) {
          closeErr = e;
        }
      }
      if (closeErr) {
        throw closeErr;
      }
    }
    function utimesMillisSync(path, atime, mtime) {
      const fd = fs.openSync(path, "r+");
      fs.futimesSync(fd, atime, mtime);
      return fs.closeSync(fd);
    }
    module2.exports = {
      utimesMillis: u(utimesMillis),
      utimesMillisSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/util/stat.js
var require_stat = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/util/stat.js"(exports2, module2) {
    "use strict";
    var fs = require_fs();
    var path = require("path");
    var u = require_universalify().fromPromise;
    function getStats(src, dest, opts) {
      const statFunc = opts.dereference ? (file) => fs.stat(file, { bigint: true }) : (file) => fs.lstat(file, { bigint: true });
      return Promise.all([
        statFunc(src),
        statFunc(dest).catch((err) => {
          if (err.code === "ENOENT") return null;
          throw err;
        })
      ]).then(([srcStat, destStat]) => ({ srcStat, destStat }));
    }
    function getStatsSync(src, dest, opts) {
      let destStat;
      const statFunc = opts.dereference ? (file) => fs.statSync(file, { bigint: true }) : (file) => fs.lstatSync(file, { bigint: true });
      const srcStat = statFunc(src);
      try {
        destStat = statFunc(dest);
      } catch (err) {
        if (err.code === "ENOENT") return { srcStat, destStat: null };
        throw err;
      }
      return { srcStat, destStat };
    }
    async function checkPaths(src, dest, funcName, opts) {
      const { srcStat, destStat } = await getStats(src, dest, opts);
      if (destStat) {
        if (areIdentical(srcStat, destStat)) {
          const srcBaseName = path.basename(src);
          const destBaseName = path.basename(dest);
          if (funcName === "move" && srcBaseName !== destBaseName && srcBaseName.toLowerCase() === destBaseName.toLowerCase()) {
            return { srcStat, destStat, isChangingCase: true };
          }
          throw new Error("Source and destination must not be the same.");
        }
        if (srcStat.isDirectory() && !destStat.isDirectory()) {
          throw new Error(`Cannot overwrite non-directory '${dest}' with directory '${src}'.`);
        }
        if (!srcStat.isDirectory() && destStat.isDirectory()) {
          throw new Error(`Cannot overwrite directory '${dest}' with non-directory '${src}'.`);
        }
      }
      if (srcStat.isDirectory() && isSrcSubdir(src, dest)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return { srcStat, destStat };
    }
    function checkPathsSync(src, dest, funcName, opts) {
      const { srcStat, destStat } = getStatsSync(src, dest, opts);
      if (destStat) {
        if (areIdentical(srcStat, destStat)) {
          const srcBaseName = path.basename(src);
          const destBaseName = path.basename(dest);
          if (funcName === "move" && srcBaseName !== destBaseName && srcBaseName.toLowerCase() === destBaseName.toLowerCase()) {
            return { srcStat, destStat, isChangingCase: true };
          }
          throw new Error("Source and destination must not be the same.");
        }
        if (srcStat.isDirectory() && !destStat.isDirectory()) {
          throw new Error(`Cannot overwrite non-directory '${dest}' with directory '${src}'.`);
        }
        if (!srcStat.isDirectory() && destStat.isDirectory()) {
          throw new Error(`Cannot overwrite directory '${dest}' with non-directory '${src}'.`);
        }
      }
      if (srcStat.isDirectory() && isSrcSubdir(src, dest)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return { srcStat, destStat };
    }
    async function checkParentPaths(src, srcStat, dest, funcName) {
      const srcParent = path.resolve(path.dirname(src));
      const destParent = path.resolve(path.dirname(dest));
      if (destParent === srcParent || destParent === path.parse(destParent).root) return;
      let destStat;
      try {
        destStat = await fs.stat(destParent, { bigint: true });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
      if (areIdentical(srcStat, destStat)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return checkParentPaths(src, srcStat, destParent, funcName);
    }
    function checkParentPathsSync(src, srcStat, dest, funcName) {
      const srcParent = path.resolve(path.dirname(src));
      const destParent = path.resolve(path.dirname(dest));
      if (destParent === srcParent || destParent === path.parse(destParent).root) return;
      let destStat;
      try {
        destStat = fs.statSync(destParent, { bigint: true });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
      if (areIdentical(srcStat, destStat)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return checkParentPathsSync(src, srcStat, destParent, funcName);
    }
    function areIdentical(srcStat, destStat) {
      return destStat.ino && destStat.dev && destStat.ino === srcStat.ino && destStat.dev === srcStat.dev;
    }
    function isSrcSubdir(src, dest) {
      const srcArr = path.resolve(src).split(path.sep).filter((i) => i);
      const destArr = path.resolve(dest).split(path.sep).filter((i) => i);
      return srcArr.every((cur, i) => destArr[i] === cur);
    }
    function errMsg(src, dest, funcName) {
      return `Cannot ${funcName} '${src}' to a subdirectory of itself, '${dest}'.`;
    }
    module2.exports = {
      // checkPaths
      checkPaths: u(checkPaths),
      checkPathsSync,
      // checkParent
      checkParentPaths: u(checkParentPaths),
      checkParentPathsSync,
      // Misc
      isSrcSubdir,
      areIdentical
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/copy/copy.js
var require_copy = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/copy/copy.js"(exports2, module2) {
    "use strict";
    var fs = require_fs();
    var path = require("path");
    var { mkdirs } = require_mkdirs();
    var { pathExists } = require_path_exists();
    var { utimesMillis } = require_utimes();
    var stat = require_stat();
    async function copy(src, dest, opts = {}) {
      if (typeof opts === "function") {
        opts = { filter: opts };
      }
      opts.clobber = "clobber" in opts ? !!opts.clobber : true;
      opts.overwrite = "overwrite" in opts ? !!opts.overwrite : opts.clobber;
      if (opts.preserveTimestamps && process.arch === "ia32") {
        process.emitWarning(
          "Using the preserveTimestamps option in 32-bit node is not recommended;\n\n	see https://github.com/jprichardson/node-fs-extra/issues/269",
          "Warning",
          "fs-extra-WARN0001"
        );
      }
      const { srcStat, destStat } = await stat.checkPaths(src, dest, "copy", opts);
      await stat.checkParentPaths(src, srcStat, dest, "copy");
      const include = await runFilter(src, dest, opts);
      if (!include) return;
      const destParent = path.dirname(dest);
      const dirExists = await pathExists(destParent);
      if (!dirExists) {
        await mkdirs(destParent);
      }
      await getStatsAndPerformCopy(destStat, src, dest, opts);
    }
    async function runFilter(src, dest, opts) {
      if (!opts.filter) return true;
      return opts.filter(src, dest);
    }
    async function getStatsAndPerformCopy(destStat, src, dest, opts) {
      const statFn = opts.dereference ? fs.stat : fs.lstat;
      const srcStat = await statFn(src);
      if (srcStat.isDirectory()) return onDir(srcStat, destStat, src, dest, opts);
      if (srcStat.isFile() || srcStat.isCharacterDevice() || srcStat.isBlockDevice()) return onFile(srcStat, destStat, src, dest, opts);
      if (srcStat.isSymbolicLink()) return onLink(destStat, src, dest, opts);
      if (srcStat.isSocket()) throw new Error(`Cannot copy a socket file: ${src}`);
      if (srcStat.isFIFO()) throw new Error(`Cannot copy a FIFO pipe: ${src}`);
      throw new Error(`Unknown file: ${src}`);
    }
    async function onFile(srcStat, destStat, src, dest, opts) {
      if (!destStat) return copyFile(srcStat, src, dest, opts);
      if (opts.overwrite) {
        await fs.unlink(dest);
        return copyFile(srcStat, src, dest, opts);
      }
      if (opts.errorOnExist) {
        throw new Error(`'${dest}' already exists`);
      }
    }
    async function copyFile(srcStat, src, dest, opts) {
      await fs.copyFile(src, dest);
      if (opts.preserveTimestamps) {
        if (fileIsNotWritable(srcStat.mode)) {
          await makeFileWritable(dest, srcStat.mode);
        }
        const updatedSrcStat = await fs.stat(src);
        await utimesMillis(dest, updatedSrcStat.atime, updatedSrcStat.mtime);
      }
      return fs.chmod(dest, srcStat.mode);
    }
    function fileIsNotWritable(srcMode) {
      return (srcMode & 128) === 0;
    }
    function makeFileWritable(dest, srcMode) {
      return fs.chmod(dest, srcMode | 128);
    }
    async function onDir(srcStat, destStat, src, dest, opts) {
      if (!destStat) {
        await fs.mkdir(dest);
      }
      const promises = [];
      for await (const item of await fs.opendir(src)) {
        const srcItem = path.join(src, item.name);
        const destItem = path.join(dest, item.name);
        promises.push(
          runFilter(srcItem, destItem, opts).then((include) => {
            if (include) {
              return stat.checkPaths(srcItem, destItem, "copy", opts).then(({ destStat: destStat2 }) => {
                return getStatsAndPerformCopy(destStat2, srcItem, destItem, opts);
              });
            }
          })
        );
      }
      await Promise.all(promises);
      if (!destStat) {
        await fs.chmod(dest, srcStat.mode);
      }
    }
    async function onLink(destStat, src, dest, opts) {
      let resolvedSrc = await fs.readlink(src);
      if (opts.dereference) {
        resolvedSrc = path.resolve(process.cwd(), resolvedSrc);
      }
      if (!destStat) {
        return fs.symlink(resolvedSrc, dest);
      }
      let resolvedDest = null;
      try {
        resolvedDest = await fs.readlink(dest);
      } catch (e) {
        if (e.code === "EINVAL" || e.code === "UNKNOWN") return fs.symlink(resolvedSrc, dest);
        throw e;
      }
      if (opts.dereference) {
        resolvedDest = path.resolve(process.cwd(), resolvedDest);
      }
      if (stat.isSrcSubdir(resolvedSrc, resolvedDest)) {
        throw new Error(`Cannot copy '${resolvedSrc}' to a subdirectory of itself, '${resolvedDest}'.`);
      }
      if (stat.isSrcSubdir(resolvedDest, resolvedSrc)) {
        throw new Error(`Cannot overwrite '${resolvedDest}' with '${resolvedSrc}'.`);
      }
      await fs.unlink(dest);
      return fs.symlink(resolvedSrc, dest);
    }
    module2.exports = copy;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/copy/copy-sync.js
var require_copy_sync = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/copy/copy-sync.js"(exports2, module2) {
    "use strict";
    var fs = require_graceful_fs();
    var path = require("path");
    var mkdirsSync = require_mkdirs().mkdirsSync;
    var utimesMillisSync = require_utimes().utimesMillisSync;
    var stat = require_stat();
    function copySync(src, dest, opts) {
      if (typeof opts === "function") {
        opts = { filter: opts };
      }
      opts = opts || {};
      opts.clobber = "clobber" in opts ? !!opts.clobber : true;
      opts.overwrite = "overwrite" in opts ? !!opts.overwrite : opts.clobber;
      if (opts.preserveTimestamps && process.arch === "ia32") {
        process.emitWarning(
          "Using the preserveTimestamps option in 32-bit node is not recommended;\n\n	see https://github.com/jprichardson/node-fs-extra/issues/269",
          "Warning",
          "fs-extra-WARN0002"
        );
      }
      const { srcStat, destStat } = stat.checkPathsSync(src, dest, "copy", opts);
      stat.checkParentPathsSync(src, srcStat, dest, "copy");
      if (opts.filter && !opts.filter(src, dest)) return;
      const destParent = path.dirname(dest);
      if (!fs.existsSync(destParent)) mkdirsSync(destParent);
      return getStats(destStat, src, dest, opts);
    }
    function getStats(destStat, src, dest, opts) {
      const statSync = opts.dereference ? fs.statSync : fs.lstatSync;
      const srcStat = statSync(src);
      if (srcStat.isDirectory()) return onDir(srcStat, destStat, src, dest, opts);
      else if (srcStat.isFile() || srcStat.isCharacterDevice() || srcStat.isBlockDevice()) return onFile(srcStat, destStat, src, dest, opts);
      else if (srcStat.isSymbolicLink()) return onLink(destStat, src, dest, opts);
      else if (srcStat.isSocket()) throw new Error(`Cannot copy a socket file: ${src}`);
      else if (srcStat.isFIFO()) throw new Error(`Cannot copy a FIFO pipe: ${src}`);
      throw new Error(`Unknown file: ${src}`);
    }
    function onFile(srcStat, destStat, src, dest, opts) {
      if (!destStat) return copyFile(srcStat, src, dest, opts);
      return mayCopyFile(srcStat, src, dest, opts);
    }
    function mayCopyFile(srcStat, src, dest, opts) {
      if (opts.overwrite) {
        fs.unlinkSync(dest);
        return copyFile(srcStat, src, dest, opts);
      } else if (opts.errorOnExist) {
        throw new Error(`'${dest}' already exists`);
      }
    }
    function copyFile(srcStat, src, dest, opts) {
      fs.copyFileSync(src, dest);
      if (opts.preserveTimestamps) handleTimestamps(srcStat.mode, src, dest);
      return setDestMode(dest, srcStat.mode);
    }
    function handleTimestamps(srcMode, src, dest) {
      if (fileIsNotWritable(srcMode)) makeFileWritable(dest, srcMode);
      return setDestTimestamps(src, dest);
    }
    function fileIsNotWritable(srcMode) {
      return (srcMode & 128) === 0;
    }
    function makeFileWritable(dest, srcMode) {
      return setDestMode(dest, srcMode | 128);
    }
    function setDestMode(dest, srcMode) {
      return fs.chmodSync(dest, srcMode);
    }
    function setDestTimestamps(src, dest) {
      const updatedSrcStat = fs.statSync(src);
      return utimesMillisSync(dest, updatedSrcStat.atime, updatedSrcStat.mtime);
    }
    function onDir(srcStat, destStat, src, dest, opts) {
      if (!destStat) return mkDirAndCopy(srcStat.mode, src, dest, opts);
      return copyDir(src, dest, opts);
    }
    function mkDirAndCopy(srcMode, src, dest, opts) {
      fs.mkdirSync(dest);
      copyDir(src, dest, opts);
      return setDestMode(dest, srcMode);
    }
    function copyDir(src, dest, opts) {
      const dir = fs.opendirSync(src);
      try {
        let dirent;
        while ((dirent = dir.readSync()) !== null) {
          copyDirItem(dirent.name, src, dest, opts);
        }
      } finally {
        dir.closeSync();
      }
    }
    function copyDirItem(item, src, dest, opts) {
      const srcItem = path.join(src, item);
      const destItem = path.join(dest, item);
      if (opts.filter && !opts.filter(srcItem, destItem)) return;
      const { destStat } = stat.checkPathsSync(srcItem, destItem, "copy", opts);
      return getStats(destStat, srcItem, destItem, opts);
    }
    function onLink(destStat, src, dest, opts) {
      let resolvedSrc = fs.readlinkSync(src);
      if (opts.dereference) {
        resolvedSrc = path.resolve(process.cwd(), resolvedSrc);
      }
      if (!destStat) {
        return fs.symlinkSync(resolvedSrc, dest);
      } else {
        let resolvedDest;
        try {
          resolvedDest = fs.readlinkSync(dest);
        } catch (err) {
          if (err.code === "EINVAL" || err.code === "UNKNOWN") return fs.symlinkSync(resolvedSrc, dest);
          throw err;
        }
        if (opts.dereference) {
          resolvedDest = path.resolve(process.cwd(), resolvedDest);
        }
        if (stat.isSrcSubdir(resolvedSrc, resolvedDest)) {
          throw new Error(`Cannot copy '${resolvedSrc}' to a subdirectory of itself, '${resolvedDest}'.`);
        }
        if (stat.isSrcSubdir(resolvedDest, resolvedSrc)) {
          throw new Error(`Cannot overwrite '${resolvedDest}' with '${resolvedSrc}'.`);
        }
        return copyLink(resolvedSrc, dest);
      }
    }
    function copyLink(resolvedSrc, dest) {
      fs.unlinkSync(dest);
      return fs.symlinkSync(resolvedSrc, dest);
    }
    module2.exports = copySync;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/copy/index.js
var require_copy2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/copy/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    module2.exports = {
      copy: u(require_copy()),
      copySync: require_copy_sync()
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/remove/index.js
var require_remove = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/remove/index.js"(exports2, module2) {
    "use strict";
    var fs = require_graceful_fs();
    var u = require_universalify().fromCallback;
    function remove(path, callback) {
      fs.rm(path, { recursive: true, force: true }, callback);
    }
    function removeSync(path) {
      fs.rmSync(path, { recursive: true, force: true });
    }
    module2.exports = {
      remove: u(remove),
      removeSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/empty/index.js
var require_empty = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/empty/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var fs = require_fs();
    var path = require("path");
    var mkdir = require_mkdirs();
    var remove = require_remove();
    var emptyDir = u(async function emptyDir2(dir) {
      let items;
      try {
        items = await fs.readdir(dir);
      } catch {
        return mkdir.mkdirs(dir);
      }
      return Promise.all(items.map((item) => remove.remove(path.join(dir, item))));
    });
    function emptyDirSync(dir) {
      let items;
      try {
        items = fs.readdirSync(dir);
      } catch {
        return mkdir.mkdirsSync(dir);
      }
      items.forEach((item) => {
        item = path.join(dir, item);
        remove.removeSync(item);
      });
    }
    module2.exports = {
      emptyDirSync,
      emptydirSync: emptyDirSync,
      emptyDir,
      emptydir: emptyDir
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/file.js
var require_file = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/file.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var path = require("path");
    var fs = require_fs();
    var mkdir = require_mkdirs();
    async function createFile(file) {
      let stats;
      try {
        stats = await fs.stat(file);
      } catch {
      }
      if (stats && stats.isFile()) return;
      const dir = path.dirname(file);
      let dirStats = null;
      try {
        dirStats = await fs.stat(dir);
      } catch (err) {
        if (err.code === "ENOENT") {
          await mkdir.mkdirs(dir);
          await fs.writeFile(file, "");
          return;
        } else {
          throw err;
        }
      }
      if (dirStats.isDirectory()) {
        await fs.writeFile(file, "");
      } else {
        await fs.readdir(dir);
      }
    }
    function createFileSync(file) {
      let stats;
      try {
        stats = fs.statSync(file);
      } catch {
      }
      if (stats && stats.isFile()) return;
      const dir = path.dirname(file);
      try {
        if (!fs.statSync(dir).isDirectory()) {
          fs.readdirSync(dir);
        }
      } catch (err) {
        if (err && err.code === "ENOENT") mkdir.mkdirsSync(dir);
        else throw err;
      }
      fs.writeFileSync(file, "");
    }
    module2.exports = {
      createFile: u(createFile),
      createFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/link.js
var require_link = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/link.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var path = require("path");
    var fs = require_fs();
    var mkdir = require_mkdirs();
    var { pathExists } = require_path_exists();
    var { areIdentical } = require_stat();
    async function createLink(srcpath, dstpath) {
      let dstStat;
      try {
        dstStat = await fs.lstat(dstpath);
      } catch {
      }
      let srcStat;
      try {
        srcStat = await fs.lstat(srcpath);
      } catch (err) {
        err.message = err.message.replace("lstat", "ensureLink");
        throw err;
      }
      if (dstStat && areIdentical(srcStat, dstStat)) return;
      const dir = path.dirname(dstpath);
      const dirExists = await pathExists(dir);
      if (!dirExists) {
        await mkdir.mkdirs(dir);
      }
      await fs.link(srcpath, dstpath);
    }
    function createLinkSync(srcpath, dstpath) {
      let dstStat;
      try {
        dstStat = fs.lstatSync(dstpath);
      } catch {
      }
      try {
        const srcStat = fs.lstatSync(srcpath);
        if (dstStat && areIdentical(srcStat, dstStat)) return;
      } catch (err) {
        err.message = err.message.replace("lstat", "ensureLink");
        throw err;
      }
      const dir = path.dirname(dstpath);
      const dirExists = fs.existsSync(dir);
      if (dirExists) return fs.linkSync(srcpath, dstpath);
      mkdir.mkdirsSync(dir);
      return fs.linkSync(srcpath, dstpath);
    }
    module2.exports = {
      createLink: u(createLink),
      createLinkSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/symlink-paths.js
var require_symlink_paths = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/symlink-paths.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    var fs = require_fs();
    var { pathExists } = require_path_exists();
    var u = require_universalify().fromPromise;
    async function symlinkPaths(srcpath, dstpath) {
      if (path.isAbsolute(srcpath)) {
        try {
          await fs.lstat(srcpath);
        } catch (err) {
          err.message = err.message.replace("lstat", "ensureSymlink");
          throw err;
        }
        return {
          toCwd: srcpath,
          toDst: srcpath
        };
      }
      const dstdir = path.dirname(dstpath);
      const relativeToDst = path.join(dstdir, srcpath);
      const exists = await pathExists(relativeToDst);
      if (exists) {
        return {
          toCwd: relativeToDst,
          toDst: srcpath
        };
      }
      try {
        await fs.lstat(srcpath);
      } catch (err) {
        err.message = err.message.replace("lstat", "ensureSymlink");
        throw err;
      }
      return {
        toCwd: srcpath,
        toDst: path.relative(dstdir, srcpath)
      };
    }
    function symlinkPathsSync(srcpath, dstpath) {
      if (path.isAbsolute(srcpath)) {
        const exists2 = fs.existsSync(srcpath);
        if (!exists2) throw new Error("absolute srcpath does not exist");
        return {
          toCwd: srcpath,
          toDst: srcpath
        };
      }
      const dstdir = path.dirname(dstpath);
      const relativeToDst = path.join(dstdir, srcpath);
      const exists = fs.existsSync(relativeToDst);
      if (exists) {
        return {
          toCwd: relativeToDst,
          toDst: srcpath
        };
      }
      const srcExists = fs.existsSync(srcpath);
      if (!srcExists) throw new Error("relative srcpath does not exist");
      return {
        toCwd: srcpath,
        toDst: path.relative(dstdir, srcpath)
      };
    }
    module2.exports = {
      symlinkPaths: u(symlinkPaths),
      symlinkPathsSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/symlink-type.js
var require_symlink_type = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/symlink-type.js"(exports2, module2) {
    "use strict";
    var fs = require_fs();
    var u = require_universalify().fromPromise;
    async function symlinkType(srcpath, type) {
      if (type) return type;
      let stats;
      try {
        stats = await fs.lstat(srcpath);
      } catch {
        return "file";
      }
      return stats && stats.isDirectory() ? "dir" : "file";
    }
    function symlinkTypeSync(srcpath, type) {
      if (type) return type;
      let stats;
      try {
        stats = fs.lstatSync(srcpath);
      } catch {
        return "file";
      }
      return stats && stats.isDirectory() ? "dir" : "file";
    }
    module2.exports = {
      symlinkType: u(symlinkType),
      symlinkTypeSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/symlink.js
var require_symlink = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/symlink.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var path = require("path");
    var fs = require_fs();
    var { mkdirs, mkdirsSync } = require_mkdirs();
    var { symlinkPaths, symlinkPathsSync } = require_symlink_paths();
    var { symlinkType, symlinkTypeSync } = require_symlink_type();
    var { pathExists } = require_path_exists();
    var { areIdentical } = require_stat();
    async function createSymlink(srcpath, dstpath, type) {
      let stats;
      try {
        stats = await fs.lstat(dstpath);
      } catch {
      }
      if (stats && stats.isSymbolicLink()) {
        const [srcStat, dstStat] = await Promise.all([
          fs.stat(srcpath),
          fs.stat(dstpath)
        ]);
        if (areIdentical(srcStat, dstStat)) return;
      }
      const relative = await symlinkPaths(srcpath, dstpath);
      srcpath = relative.toDst;
      const toType = await symlinkType(relative.toCwd, type);
      const dir = path.dirname(dstpath);
      if (!await pathExists(dir)) {
        await mkdirs(dir);
      }
      return fs.symlink(srcpath, dstpath, toType);
    }
    function createSymlinkSync(srcpath, dstpath, type) {
      let stats;
      try {
        stats = fs.lstatSync(dstpath);
      } catch {
      }
      if (stats && stats.isSymbolicLink()) {
        const srcStat = fs.statSync(srcpath);
        const dstStat = fs.statSync(dstpath);
        if (areIdentical(srcStat, dstStat)) return;
      }
      const relative = symlinkPathsSync(srcpath, dstpath);
      srcpath = relative.toDst;
      type = symlinkTypeSync(relative.toCwd, type);
      const dir = path.dirname(dstpath);
      const exists = fs.existsSync(dir);
      if (exists) return fs.symlinkSync(srcpath, dstpath, type);
      mkdirsSync(dir);
      return fs.symlinkSync(srcpath, dstpath, type);
    }
    module2.exports = {
      createSymlink: u(createSymlink),
      createSymlinkSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/index.js
var require_ensure = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/ensure/index.js"(exports2, module2) {
    "use strict";
    var { createFile, createFileSync } = require_file();
    var { createLink, createLinkSync } = require_link();
    var { createSymlink, createSymlinkSync } = require_symlink();
    module2.exports = {
      // file
      createFile,
      createFileSync,
      ensureFile: createFile,
      ensureFileSync: createFileSync,
      // link
      createLink,
      createLinkSync,
      ensureLink: createLink,
      ensureLinkSync: createLinkSync,
      // symlink
      createSymlink,
      createSymlinkSync,
      ensureSymlink: createSymlink,
      ensureSymlinkSync: createSymlinkSync
    };
  }
});

// ../node_modules/.pnpm/jsonfile@6.2.0/node_modules/jsonfile/utils.js
var require_utils2 = __commonJS({
  "../node_modules/.pnpm/jsonfile@6.2.0/node_modules/jsonfile/utils.js"(exports2, module2) {
    function stringify(obj, { EOL = "\n", finalEOL = true, replacer = null, spaces } = {}) {
      const EOF = finalEOL ? EOL : "";
      const str = JSON.stringify(obj, replacer, spaces);
      return str.replace(/\n/g, EOL) + EOF;
    }
    function stripBom(content) {
      if (Buffer.isBuffer(content)) content = content.toString("utf8");
      return content.replace(/^\uFEFF/, "");
    }
    module2.exports = { stringify, stripBom };
  }
});

// ../node_modules/.pnpm/jsonfile@6.2.0/node_modules/jsonfile/index.js
var require_jsonfile = __commonJS({
  "../node_modules/.pnpm/jsonfile@6.2.0/node_modules/jsonfile/index.js"(exports2, module2) {
    var _fs;
    try {
      _fs = require_graceful_fs();
    } catch (_) {
      _fs = require("fs");
    }
    var universalify = require_universalify();
    var { stringify, stripBom } = require_utils2();
    async function _readFile(file, options = {}) {
      if (typeof options === "string") {
        options = { encoding: options };
      }
      const fs = options.fs || _fs;
      const shouldThrow = "throws" in options ? options.throws : true;
      let data = await universalify.fromCallback(fs.readFile)(file, options);
      data = stripBom(data);
      let obj;
      try {
        obj = JSON.parse(data, options ? options.reviver : null);
      } catch (err) {
        if (shouldThrow) {
          err.message = `${file}: ${err.message}`;
          throw err;
        } else {
          return null;
        }
      }
      return obj;
    }
    var readFile = universalify.fromPromise(_readFile);
    function readFileSync(file, options = {}) {
      if (typeof options === "string") {
        options = { encoding: options };
      }
      const fs = options.fs || _fs;
      const shouldThrow = "throws" in options ? options.throws : true;
      try {
        let content = fs.readFileSync(file, options);
        content = stripBom(content);
        return JSON.parse(content, options.reviver);
      } catch (err) {
        if (shouldThrow) {
          err.message = `${file}: ${err.message}`;
          throw err;
        } else {
          return null;
        }
      }
    }
    async function _writeFile(file, obj, options = {}) {
      const fs = options.fs || _fs;
      const str = stringify(obj, options);
      await universalify.fromCallback(fs.writeFile)(file, str, options);
    }
    var writeFile = universalify.fromPromise(_writeFile);
    function writeFileSync(file, obj, options = {}) {
      const fs = options.fs || _fs;
      const str = stringify(obj, options);
      return fs.writeFileSync(file, str, options);
    }
    module2.exports = {
      readFile,
      readFileSync,
      writeFile,
      writeFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/jsonfile.js
var require_jsonfile2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/jsonfile.js"(exports2, module2) {
    "use strict";
    var jsonFile = require_jsonfile();
    module2.exports = {
      // jsonfile exports
      readJson: jsonFile.readFile,
      readJsonSync: jsonFile.readFileSync,
      writeJson: jsonFile.writeFile,
      writeJsonSync: jsonFile.writeFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/output-file/index.js
var require_output_file = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/output-file/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var fs = require_fs();
    var path = require("path");
    var mkdir = require_mkdirs();
    var pathExists = require_path_exists().pathExists;
    async function outputFile(file, data, encoding = "utf-8") {
      const dir = path.dirname(file);
      if (!await pathExists(dir)) {
        await mkdir.mkdirs(dir);
      }
      return fs.writeFile(file, data, encoding);
    }
    function outputFileSync(file, ...args) {
      const dir = path.dirname(file);
      if (!fs.existsSync(dir)) {
        mkdir.mkdirsSync(dir);
      }
      fs.writeFileSync(file, ...args);
    }
    module2.exports = {
      outputFile: u(outputFile),
      outputFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/output-json.js
var require_output_json = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/output-json.js"(exports2, module2) {
    "use strict";
    var { stringify } = require_utils2();
    var { outputFile } = require_output_file();
    async function outputJson(file, data, options = {}) {
      const str = stringify(data, options);
      await outputFile(file, str, options);
    }
    module2.exports = outputJson;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/output-json-sync.js
var require_output_json_sync = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/output-json-sync.js"(exports2, module2) {
    "use strict";
    var { stringify } = require_utils2();
    var { outputFileSync } = require_output_file();
    function outputJsonSync(file, data, options) {
      const str = stringify(data, options);
      outputFileSync(file, str, options);
    }
    module2.exports = outputJsonSync;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/index.js
var require_json = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/json/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var jsonFile = require_jsonfile2();
    jsonFile.outputJson = u(require_output_json());
    jsonFile.outputJsonSync = require_output_json_sync();
    jsonFile.outputJSON = jsonFile.outputJson;
    jsonFile.outputJSONSync = jsonFile.outputJsonSync;
    jsonFile.writeJSON = jsonFile.writeJson;
    jsonFile.writeJSONSync = jsonFile.writeJsonSync;
    jsonFile.readJSON = jsonFile.readJson;
    jsonFile.readJSONSync = jsonFile.readJsonSync;
    module2.exports = jsonFile;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/move/move.js
var require_move = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/move/move.js"(exports2, module2) {
    "use strict";
    var fs = require_fs();
    var path = require("path");
    var { copy } = require_copy2();
    var { remove } = require_remove();
    var { mkdirp } = require_mkdirs();
    var { pathExists } = require_path_exists();
    var stat = require_stat();
    async function move(src, dest, opts = {}) {
      const overwrite = opts.overwrite || opts.clobber || false;
      const { srcStat, isChangingCase = false } = await stat.checkPaths(src, dest, "move", opts);
      await stat.checkParentPaths(src, srcStat, dest, "move");
      const destParent = path.dirname(dest);
      const parsedParentPath = path.parse(destParent);
      if (parsedParentPath.root !== destParent) {
        await mkdirp(destParent);
      }
      return doRename(src, dest, overwrite, isChangingCase);
    }
    async function doRename(src, dest, overwrite, isChangingCase) {
      if (!isChangingCase) {
        if (overwrite) {
          await remove(dest);
        } else if (await pathExists(dest)) {
          throw new Error("dest already exists.");
        }
      }
      try {
        await fs.rename(src, dest);
      } catch (err) {
        if (err.code !== "EXDEV") {
          throw err;
        }
        await moveAcrossDevice(src, dest, overwrite);
      }
    }
    async function moveAcrossDevice(src, dest, overwrite) {
      const opts = {
        overwrite,
        errorOnExist: true,
        preserveTimestamps: true
      };
      await copy(src, dest, opts);
      return remove(src);
    }
    module2.exports = move;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/move/move-sync.js
var require_move_sync = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/move/move-sync.js"(exports2, module2) {
    "use strict";
    var fs = require_graceful_fs();
    var path = require("path");
    var copySync = require_copy2().copySync;
    var removeSync = require_remove().removeSync;
    var mkdirpSync = require_mkdirs().mkdirpSync;
    var stat = require_stat();
    function moveSync(src, dest, opts) {
      opts = opts || {};
      const overwrite = opts.overwrite || opts.clobber || false;
      const { srcStat, isChangingCase = false } = stat.checkPathsSync(src, dest, "move", opts);
      stat.checkParentPathsSync(src, srcStat, dest, "move");
      if (!isParentRoot(dest)) mkdirpSync(path.dirname(dest));
      return doRename(src, dest, overwrite, isChangingCase);
    }
    function isParentRoot(dest) {
      const parent = path.dirname(dest);
      const parsedPath = path.parse(parent);
      return parsedPath.root === parent;
    }
    function doRename(src, dest, overwrite, isChangingCase) {
      if (isChangingCase) return rename(src, dest, overwrite);
      if (overwrite) {
        removeSync(dest);
        return rename(src, dest, overwrite);
      }
      if (fs.existsSync(dest)) throw new Error("dest already exists.");
      return rename(src, dest, overwrite);
    }
    function rename(src, dest, overwrite) {
      try {
        fs.renameSync(src, dest);
      } catch (err) {
        if (err.code !== "EXDEV") throw err;
        return moveAcrossDevice(src, dest, overwrite);
      }
    }
    function moveAcrossDevice(src, dest, overwrite) {
      const opts = {
        overwrite,
        errorOnExist: true,
        preserveTimestamps: true
      };
      copySync(src, dest, opts);
      return removeSync(src);
    }
    module2.exports = moveSync;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/move/index.js
var require_move2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/move/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    module2.exports = {
      move: u(require_move()),
      moveSync: require_move_sync()
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/index.js
var require_lib3 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.0/node_modules/fs-extra/lib/index.js"(exports2, module2) {
    "use strict";
    module2.exports = {
      // Export promiseified graceful-fs:
      ...require_fs(),
      // Export extra methods:
      ...require_copy2(),
      ...require_empty(),
      ...require_ensure(),
      ...require_json(),
      ...require_mkdirs(),
      ...require_move2(),
      ...require_output_file(),
      ...require_path_exists(),
      ...require_remove()
    };
  }
});

// ../node_modules/.pnpm/rename-overwrite@6.0.2/node_modules/rename-overwrite/index.js
var require_rename_overwrite = __commonJS({
  "../node_modules/.pnpm/rename-overwrite@6.0.2/node_modules/rename-overwrite/index.js"(exports2, module2) {
    "use strict";
    var fs = require("fs");
    var { copySync, copy } = require_lib3();
    var path = require("path");
    var rimraf = require_rimraf();
    module2.exports = async function renameOverwrite(oldPath, newPath, retry = 0) {
      try {
        await fs.promises.rename(oldPath, newPath);
      } catch (err) {
        retry++;
        if (retry > 3) throw err;
        switch (err.code) {
          case "ENOTEMPTY":
          case "EEXIST":
          case "ENOTDIR":
            await rimraf(newPath);
            await renameOverwrite(oldPath, newPath, retry);
            break;
          // Windows Antivirus issues
          case "EPERM":
          case "EACCESS": {
            await rimraf(newPath);
            const start = Date.now();
            let backoff = 0;
            let lastError = err;
            while (Date.now() - start < 6e4 && (lastError.code === "EPERM" || lastError.code === "EACCESS")) {
              await new Promise((resolve) => setTimeout(resolve, backoff));
              try {
                await fs.promises.rename(oldPath, newPath);
                return;
              } catch (err2) {
                lastError = err2;
              }
              if (backoff < 100) {
                backoff += 10;
              }
            }
            throw lastError;
          }
          case "ENOENT":
            try {
              await fs.promises.stat(oldPath);
            } catch (statErr) {
              if (statErr.code === "ENOENT") {
                throw statErr;
              }
            }
            await fs.promises.mkdir(path.dirname(newPath), { recursive: true });
            await renameOverwrite(oldPath, newPath, retry);
            break;
          // Crossing filesystem boundaries so rename is not available
          case "EXDEV":
            try {
              await rimraf(newPath);
            } catch (rimrafErr) {
              if (rimrafErr.code !== "ENOENT") {
                throw rimrafErr;
              }
            }
            await copy(oldPath, newPath);
            await rimraf(oldPath);
            break;
          default:
            throw err;
        }
      }
    };
    module2.exports.sync = function renameOverwriteSync(oldPath, newPath, retry = 0) {
      try {
        fs.renameSync(oldPath, newPath);
      } catch (err) {
        retry++;
        if (retry > 3) throw err;
        switch (err.code) {
          // Windows Antivirus issues
          case "EPERM":
          case "EACCESS": {
            rimraf.sync(newPath);
            const start = Date.now();
            let backoff = 0;
            let lastError = err;
            while (Date.now() - start < 6e4 && (lastError.code === "EPERM" || lastError.code === "EACCESS")) {
              const waitUntil = Date.now() + backoff;
              while (waitUntil > Date.now()) {
              }
              try {
                fs.renameSync(oldPath, newPath);
                return;
              } catch (err2) {
                lastError = err2;
              }
              if (backoff < 100) {
                backoff += 10;
              }
            }
            throw lastError;
          }
          case "ENOTEMPTY":
          case "EEXIST":
          case "ENOTDIR":
            rimraf.sync(newPath);
            fs.renameSync(oldPath, newPath);
            return;
          case "ENOENT":
            fs.mkdirSync(path.dirname(newPath), { recursive: true });
            renameOverwriteSync(oldPath, newPath, retry);
            return;
          // Crossing filesystem boundaries so rename is not available
          case "EXDEV":
            try {
              rimraf.sync(newPath);
            } catch (rimrafErr) {
              if (rimrafErr.code !== "ENOENT") {
                throw rimrafErr;
              }
            }
            copySync(oldPath, newPath);
            rimraf.sync(oldPath);
            break;
          default:
            throw err;
        }
      }
    };
  }
});

// ../store/cafs/lib/writeFile.js
var require_writeFile = __commonJS({
  "../store/cafs/lib/writeFile.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.writeFile = writeFile;
    var path_1 = __importDefault(require("path"));
    var graceful_fs_1 = __importDefault(require_lib());
    var dirs = /* @__PURE__ */ new Set();
    function writeFile(fileDest, buffer, mode) {
      makeDirForFile(fileDest);
      graceful_fs_1.default.writeFileSync(fileDest, buffer, { mode });
    }
    function makeDirForFile(fileDest) {
      const dir = path_1.default.dirname(fileDest);
      if (!dirs.has(dir)) {
        graceful_fs_1.default.mkdirSync(dir, { recursive: true });
        dirs.add(dir);
      }
    }
  }
});

// ../store/cafs/lib/writeBufferToCafs.js
var require_writeBufferToCafs = __commonJS({
  "../store/cafs/lib/writeBufferToCafs.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.writeBufferToCafs = writeBufferToCafs;
    exports2.optimisticRenameOverwrite = optimisticRenameOverwrite;
    exports2.pathTemp = pathTemp;
    var fs_1 = __importDefault(require("fs"));
    var path_1 = __importDefault(require("path"));
    var worker_threads_1 = __importDefault(require("worker_threads"));
    var util_1 = __importDefault(require("util"));
    var rename_overwrite_1 = __importDefault(require_rename_overwrite());
    var checkPkgFilesIntegrity_js_1 = require_checkPkgFilesIntegrity();
    var writeFile_js_1 = require_writeFile();
    function writeBufferToCafs(locker, storeDir, buffer, fileDest, mode, integrity) {
      fileDest = path_1.default.join(storeDir, fileDest);
      if (locker.has(fileDest)) {
        return {
          checkedAt: locker.get(fileDest),
          filePath: fileDest
        };
      }
      if (existsSame(fileDest, integrity)) {
        return {
          checkedAt: Date.now(),
          filePath: fileDest
        };
      }
      const temp = pathTemp(fileDest);
      (0, writeFile_js_1.writeFile)(temp, buffer, mode);
      const birthtimeMs = Date.now();
      optimisticRenameOverwrite(temp, fileDest);
      locker.set(fileDest, birthtimeMs);
      return {
        checkedAt: birthtimeMs,
        filePath: fileDest
      };
    }
    function optimisticRenameOverwrite(temp, fileDest) {
      try {
        rename_overwrite_1.default.sync(temp, fileDest);
      } catch (err) {
        if (!(util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") || !fs_1.default.existsSync(fileDest))
          throw err;
      }
    }
    function pathTemp(file) {
      const basename = removeSuffix(path_1.default.basename(file));
      return path_1.default.join(path_1.default.dirname(file), `${basename}${process.pid}${worker_threads_1.default.threadId}`);
    }
    function removeSuffix(filePath) {
      const dashPosition = filePath.indexOf("-");
      if (dashPosition === -1)
        return filePath;
      const withoutSuffix = filePath.substring(0, dashPosition);
      if (filePath.substring(dashPosition) === "-exec") {
        return `${withoutSuffix}x`;
      }
      return withoutSuffix;
    }
    function existsSame(filename, integrity) {
      const existingFile = fs_1.default.statSync(filename, { throwIfNoEntry: false });
      if (!existingFile)
        return false;
      return (0, checkPkgFilesIntegrity_js_1.verifyFileIntegrity)(filename, {
        size: existingFile.size,
        integrity
      }).passed;
    }
  }
});

// ../store/cafs/lib/index.js
var require_lib4 = __commonJS({
  "../store/cafs/lib/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.optimisticRenameOverwrite = exports2.getIndexFilePathInCafs = exports2.getFilePathByModeInCafs = exports2.readManifestFromStore = exports2.checkPkgFilesIntegrity = void 0;
    exports2.createCafs = createCafs;
    var ssri_1 = __importDefault(require_lib2());
    var addFilesFromDir_js_1 = require_addFilesFromDir();
    var addFilesFromTarball_js_1 = require_addFilesFromTarball();
    var checkPkgFilesIntegrity_js_1 = require_checkPkgFilesIntegrity();
    Object.defineProperty(exports2, "checkPkgFilesIntegrity", { enumerable: true, get: function() {
      return checkPkgFilesIntegrity_js_1.checkPkgFilesIntegrity;
    } });
    var readManifestFromStore_js_1 = require_readManifestFromStore();
    Object.defineProperty(exports2, "readManifestFromStore", { enumerable: true, get: function() {
      return readManifestFromStore_js_1.readManifestFromStore;
    } });
    var getFilePathInCafs_js_1 = require_getFilePathInCafs();
    Object.defineProperty(exports2, "getIndexFilePathInCafs", { enumerable: true, get: function() {
      return getFilePathInCafs_js_1.getIndexFilePathInCafs;
    } });
    Object.defineProperty(exports2, "getFilePathByModeInCafs", { enumerable: true, get: function() {
      return getFilePathInCafs_js_1.getFilePathByModeInCafs;
    } });
    var writeBufferToCafs_js_1 = require_writeBufferToCafs();
    Object.defineProperty(exports2, "optimisticRenameOverwrite", { enumerable: true, get: function() {
      return writeBufferToCafs_js_1.optimisticRenameOverwrite;
    } });
    function createCafs(storeDir, { ignoreFile, cafsLocker } = {}) {
      const _writeBufferToCafs = writeBufferToCafs_js_1.writeBufferToCafs.bind(null, cafsLocker ?? /* @__PURE__ */ new Map(), storeDir);
      const addBuffer = addBufferToCafs.bind(null, _writeBufferToCafs);
      return {
        addFilesFromDir: addFilesFromDir_js_1.addFilesFromDir.bind(null, addBuffer),
        addFilesFromTarball: addFilesFromTarball_js_1.addFilesFromTarball.bind(null, addBuffer, ignoreFile ?? null),
        addFile: addBuffer,
        getIndexFilePathInCafs: getFilePathInCafs_js_1.getIndexFilePathInCafs.bind(null, storeDir),
        getFilePathByModeInCafs: getFilePathInCafs_js_1.getFilePathByModeInCafs.bind(null, storeDir)
      };
    }
    function addBufferToCafs(writeBufferToCafs, buffer, mode) {
      const integrity = ssri_1.default.fromData(buffer);
      const isExecutable = (0, getFilePathInCafs_js_1.modeIsExecutable)(mode);
      const fileDest = (0, getFilePathInCafs_js_1.contentPathFromHex)(isExecutable ? "exec" : "nonexec", integrity.hexDigest());
      const { checkedAt, filePath } = writeBufferToCafs(buffer, fileDest, isExecutable ? 493 : void 0, integrity);
      return { checkedAt, integrity, filePath };
    }
  }
});

// ../node_modules/.pnpm/fast-safe-stringify@2.1.1/node_modules/fast-safe-stringify/index.js
var require_fast_safe_stringify = __commonJS({
  "../node_modules/.pnpm/fast-safe-stringify@2.1.1/node_modules/fast-safe-stringify/index.js"(exports2, module2) {
    module2.exports = stringify;
    stringify.default = stringify;
    stringify.stable = deterministicStringify;
    stringify.stableStringify = deterministicStringify;
    var LIMIT_REPLACE_NODE = "[...]";
    var CIRCULAR_REPLACE_NODE = "[Circular]";
    var arr = [];
    var replacerStack = [];
    function defaultOptions() {
      return {
        depthLimit: Number.MAX_SAFE_INTEGER,
        edgesLimit: Number.MAX_SAFE_INTEGER
      };
    }
    function stringify(obj, replacer, spacer, options) {
      if (typeof options === "undefined") {
        options = defaultOptions();
      }
      decirc(obj, "", 0, [], void 0, 0, options);
      var res;
      try {
        if (replacerStack.length === 0) {
          res = JSON.stringify(obj, replacer, spacer);
        } else {
          res = JSON.stringify(obj, replaceGetterValues(replacer), spacer);
        }
      } catch (_) {
        return JSON.stringify("[unable to serialize, circular reference is too complex to analyze]");
      } finally {
        while (arr.length !== 0) {
          var part = arr.pop();
          if (part.length === 4) {
            Object.defineProperty(part[0], part[1], part[3]);
          } else {
            part[0][part[1]] = part[2];
          }
        }
      }
      return res;
    }
    function setReplace(replace, val, k, parent) {
      var propertyDescriptor = Object.getOwnPropertyDescriptor(parent, k);
      if (propertyDescriptor.get !== void 0) {
        if (propertyDescriptor.configurable) {
          Object.defineProperty(parent, k, { value: replace });
          arr.push([parent, k, val, propertyDescriptor]);
        } else {
          replacerStack.push([val, k, replace]);
        }
      } else {
        parent[k] = replace;
        arr.push([parent, k, val]);
      }
    }
    function decirc(val, k, edgeIndex, stack, parent, depth, options) {
      depth += 1;
      var i;
      if (typeof val === "object" && val !== null) {
        for (i = 0; i < stack.length; i++) {
          if (stack[i] === val) {
            setReplace(CIRCULAR_REPLACE_NODE, val, k, parent);
            return;
          }
        }
        if (typeof options.depthLimit !== "undefined" && depth > options.depthLimit) {
          setReplace(LIMIT_REPLACE_NODE, val, k, parent);
          return;
        }
        if (typeof options.edgesLimit !== "undefined" && edgeIndex + 1 > options.edgesLimit) {
          setReplace(LIMIT_REPLACE_NODE, val, k, parent);
          return;
        }
        stack.push(val);
        if (Array.isArray(val)) {
          for (i = 0; i < val.length; i++) {
            decirc(val[i], i, i, stack, val, depth, options);
          }
        } else {
          var keys = Object.keys(val);
          for (i = 0; i < keys.length; i++) {
            var key = keys[i];
            decirc(val[key], key, i, stack, val, depth, options);
          }
        }
        stack.pop();
      }
    }
    function compareFunction(a, b) {
      if (a < b) {
        return -1;
      }
      if (a > b) {
        return 1;
      }
      return 0;
    }
    function deterministicStringify(obj, replacer, spacer, options) {
      if (typeof options === "undefined") {
        options = defaultOptions();
      }
      var tmp = deterministicDecirc(obj, "", 0, [], void 0, 0, options) || obj;
      var res;
      try {
        if (replacerStack.length === 0) {
          res = JSON.stringify(tmp, replacer, spacer);
        } else {
          res = JSON.stringify(tmp, replaceGetterValues(replacer), spacer);
        }
      } catch (_) {
        return JSON.stringify("[unable to serialize, circular reference is too complex to analyze]");
      } finally {
        while (arr.length !== 0) {
          var part = arr.pop();
          if (part.length === 4) {
            Object.defineProperty(part[0], part[1], part[3]);
          } else {
            part[0][part[1]] = part[2];
          }
        }
      }
      return res;
    }
    function deterministicDecirc(val, k, edgeIndex, stack, parent, depth, options) {
      depth += 1;
      var i;
      if (typeof val === "object" && val !== null) {
        for (i = 0; i < stack.length; i++) {
          if (stack[i] === val) {
            setReplace(CIRCULAR_REPLACE_NODE, val, k, parent);
            return;
          }
        }
        try {
          if (typeof val.toJSON === "function") {
            return;
          }
        } catch (_) {
          return;
        }
        if (typeof options.depthLimit !== "undefined" && depth > options.depthLimit) {
          setReplace(LIMIT_REPLACE_NODE, val, k, parent);
          return;
        }
        if (typeof options.edgesLimit !== "undefined" && edgeIndex + 1 > options.edgesLimit) {
          setReplace(LIMIT_REPLACE_NODE, val, k, parent);
          return;
        }
        stack.push(val);
        if (Array.isArray(val)) {
          for (i = 0; i < val.length; i++) {
            deterministicDecirc(val[i], i, i, stack, val, depth, options);
          }
        } else {
          var tmp = {};
          var keys = Object.keys(val).sort(compareFunction);
          for (i = 0; i < keys.length; i++) {
            var key = keys[i];
            deterministicDecirc(val[key], key, i, stack, val, depth, options);
            tmp[key] = val[key];
          }
          if (typeof parent !== "undefined") {
            arr.push([parent, k, val]);
            parent[k] = tmp;
          } else {
            return tmp;
          }
        }
        stack.pop();
      }
    }
    function replaceGetterValues(replacer) {
      replacer = typeof replacer !== "undefined" ? replacer : function(k, v) {
        return v;
      };
      return function(key, val) {
        if (replacerStack.length > 0) {
          for (var i = 0; i < replacerStack.length; i++) {
            var part = replacerStack[i];
            if (part[1] === key && part[0] === val) {
              val = part[2];
              replacerStack.splice(i, 1);
              break;
            }
          }
        }
        return replacer.call(this, key, val);
      };
    }
  }
});

// ../node_modules/.pnpm/individual@3.0.0/node_modules/individual/index.js
var require_individual = __commonJS({
  "../node_modules/.pnpm/individual@3.0.0/node_modules/individual/index.js"(exports2, module2) {
    "use strict";
    var root = typeof window !== "undefined" ? window : typeof global !== "undefined" ? global : {};
    module2.exports = Individual;
    function Individual(key, value) {
      if (key in root) {
        return root[key];
      }
      root[key] = value;
      return value;
    }
  }
});

// ../node_modules/.pnpm/bole@5.0.17/node_modules/bole/format.js
var require_format = __commonJS({
  "../node_modules/.pnpm/bole@5.0.17/node_modules/bole/format.js"(exports2, module2) {
    var utilformat = require("util").format;
    function format(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16) {
      if (a16 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16);
      }
      if (a15 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15);
      }
      if (a14 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14);
      }
      if (a13 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13);
      }
      if (a12 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12);
      }
      if (a11 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11);
      }
      if (a10 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9, a10);
      }
      if (a9 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8, a9);
      }
      if (a8 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7, a8);
      }
      if (a7 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6, a7);
      }
      if (a6 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5, a6);
      }
      if (a5 !== void 0) {
        return utilformat(a1, a2, a3, a4, a5);
      }
      if (a4 !== void 0) {
        return utilformat(a1, a2, a3, a4);
      }
      if (a3 !== void 0) {
        return utilformat(a1, a2, a3);
      }
      if (a2 !== void 0) {
        return utilformat(a1, a2);
      }
      return a1;
    }
    module2.exports = format;
  }
});

// ../node_modules/.pnpm/bole@5.0.17/node_modules/bole/bole.js
var require_bole = __commonJS({
  "../node_modules/.pnpm/bole@5.0.17/node_modules/bole/bole.js"(exports2, module2) {
    "use strict";
    var _stringify = require_fast_safe_stringify();
    var individual = require_individual()("$$bole", { fastTime: false });
    var format = require_format();
    var levels = "debug info warn error".split(" ");
    var os = require("os");
    var pid = process.pid;
    var hasObjMode = false;
    var scache = [];
    var hostname;
    try {
      hostname = os.hostname();
    } catch (e) {
      hostname = os.version().indexOf("Windows 7 ") === 0 ? "windows7" : "hostname-unknown";
    }
    var hostnameSt = _stringify(hostname);
    for (const level of levels) {
      scache[level] = ',"hostname":' + hostnameSt + ',"pid":' + pid + ',"level":"' + level;
      Number(scache[level]);
      if (!Array.isArray(individual[level])) {
        individual[level] = [];
      }
    }
    function stackToString(e) {
      let s = e.stack;
      let ce;
      if (typeof e.cause === "function" && (ce = e.cause())) {
        s += "\nCaused by: " + stackToString(ce);
      }
      return s;
    }
    function errorToOut(err, out) {
      out.err = {
        name: err.name,
        message: err.message,
        code: err.code,
        // perhaps
        stack: stackToString(err)
      };
    }
    function requestToOut(req, out) {
      out.req = {
        method: req.method,
        url: req.url,
        headers: req.headers,
        remoteAddress: req.connection.remoteAddress,
        remotePort: req.connection.remotePort
      };
    }
    function objectToOut(obj, out) {
      for (const k in obj) {
        if (Object.prototype.hasOwnProperty.call(obj, k) && obj[k] !== void 0) {
          out[k] = obj[k];
        }
      }
    }
    function objectMode(stream) {
      return stream._writableState && stream._writableState.objectMode === true;
    }
    function stringify(level, name, message, obj) {
      let s = '{"time":' + (individual.fastTime ? Date.now() : '"' + (/* @__PURE__ */ new Date()).toISOString() + '"') + scache[level] + '","name":' + name + (message !== void 0 ? ',"message":' + _stringify(message) : "");
      for (const k in obj) {
        s += "," + _stringify(k) + ":" + _stringify(obj[k]);
      }
      s += "}";
      Number(s);
      return s;
    }
    function extend(level, name, message, obj) {
      const newObj = {
        time: individual.fastTime ? Date.now() : (/* @__PURE__ */ new Date()).toISOString(),
        hostname,
        pid,
        level,
        name
      };
      if (message !== void 0) {
        obj.message = message;
      }
      for (const k in obj) {
        newObj[k] = obj[k];
      }
      return newObj;
    }
    function levelLogger(level, name) {
      const outputs = individual[level];
      const nameSt = _stringify(name);
      return function namedLevelLogger(inp, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16) {
        if (outputs.length === 0) {
          return;
        }
        const out = {};
        let objectOut;
        let i = 0;
        const l = outputs.length;
        let stringified;
        let message;
        if (typeof inp === "string" || inp == null) {
          if (!(message = format(inp, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16))) {
            message = void 0;
          }
        } else {
          if (inp instanceof Error) {
            if (typeof a2 === "object") {
              objectToOut(a2, out);
              errorToOut(inp, out);
              if (!(message = format(a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16))) {
                message = void 0;
              }
            } else {
              errorToOut(inp, out);
              if (!(message = format(a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16))) {
                message = void 0;
              }
            }
          } else {
            if (!(message = format(a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16))) {
              message = void 0;
            }
          }
          if (typeof inp === "boolean") {
            message = String(inp);
          } else if (typeof inp === "object" && !(inp instanceof Error)) {
            if (inp.method && inp.url && inp.headers && inp.socket) {
              requestToOut(inp, out);
            } else {
              objectToOut(inp, out);
            }
          }
        }
        if (l === 1 && !hasObjMode) {
          outputs[0].write(Buffer.from(stringify(level, nameSt, message, out) + "\n"));
          return;
        }
        for (; i < l; i++) {
          if (objectMode(outputs[i])) {
            if (objectOut === void 0) {
              objectOut = extend(level, name, message, out);
            }
            outputs[i].write(objectOut);
          } else {
            if (stringified === void 0) {
              stringified = Buffer.from(stringify(level, nameSt, message, out) + "\n");
            }
            outputs[i].write(stringified);
          }
        }
      };
    }
    function bole(name) {
      function boleLogger(subname) {
        return bole(name + ":" + subname);
      }
      function makeLogger(p, level) {
        p[level] = levelLogger(level, name);
        return p;
      }
      return levels.reduce(makeLogger, boleLogger);
    }
    bole.output = function output(opt) {
      let b = false;
      if (Array.isArray(opt)) {
        opt.forEach(bole.output);
        return bole;
      }
      if (typeof opt.level !== "string") {
        throw new TypeError('Must provide a "level" option');
      }
      for (const level of levels) {
        if (!b && level === opt.level) {
          b = true;
        }
        if (b) {
          if (opt.stream && objectMode(opt.stream)) {
            hasObjMode = true;
          }
          individual[level].push(opt.stream);
        }
      }
      return bole;
    };
    bole.reset = function reset() {
      for (const level of levels) {
        individual[level].splice(0, individual[level].length);
      }
      individual.fastTime = false;
      return bole;
    };
    bole.setFastTime = function setFastTime(b) {
      if (!arguments.length) {
        individual.fastTime = true;
      } else {
        individual.fastTime = b;
      }
      return bole;
    };
    module2.exports = bole;
  }
});

// ../packages/logger/lib/logger.js
var require_logger = __commonJS({
  "../packages/logger/lib/logger.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.logger = void 0;
    exports2.globalWarn = globalWarn;
    exports2.globalInfo = globalInfo;
    var bole_1 = __importDefault(require_bole());
    bole_1.default.setFastTime();
    exports2.logger = (0, bole_1.default)("pnpm");
    var globalLogger = (0, bole_1.default)("pnpm:global");
    function globalWarn(message) {
      globalLogger.warn(message);
    }
    function globalInfo(message) {
      globalLogger.info(message);
    }
  }
});

// ../node_modules/.pnpm/split2@4.2.0/node_modules/split2/index.js
var require_split2 = __commonJS({
  "../node_modules/.pnpm/split2@4.2.0/node_modules/split2/index.js"(exports2, module2) {
    "use strict";
    var { Transform } = require("stream");
    var { StringDecoder } = require("string_decoder");
    var kLast = Symbol("last");
    var kDecoder = Symbol("decoder");
    function transform(chunk, enc, cb) {
      let list;
      if (this.overflow) {
        const buf = this[kDecoder].write(chunk);
        list = buf.split(this.matcher);
        if (list.length === 1) return cb();
        list.shift();
        this.overflow = false;
      } else {
        this[kLast] += this[kDecoder].write(chunk);
        list = this[kLast].split(this.matcher);
      }
      this[kLast] = list.pop();
      for (let i = 0; i < list.length; i++) {
        try {
          push(this, this.mapper(list[i]));
        } catch (error) {
          return cb(error);
        }
      }
      this.overflow = this[kLast].length > this.maxLength;
      if (this.overflow && !this.skipOverflow) {
        cb(new Error("maximum buffer reached"));
        return;
      }
      cb();
    }
    function flush(cb) {
      this[kLast] += this[kDecoder].end();
      if (this[kLast]) {
        try {
          push(this, this.mapper(this[kLast]));
        } catch (error) {
          return cb(error);
        }
      }
      cb();
    }
    function push(self2, val) {
      if (val !== void 0) {
        self2.push(val);
      }
    }
    function noop(incoming) {
      return incoming;
    }
    function split(matcher, mapper, options) {
      matcher = matcher || /\r?\n/;
      mapper = mapper || noop;
      options = options || {};
      switch (arguments.length) {
        case 1:
          if (typeof matcher === "function") {
            mapper = matcher;
            matcher = /\r?\n/;
          } else if (typeof matcher === "object" && !(matcher instanceof RegExp) && !matcher[Symbol.split]) {
            options = matcher;
            matcher = /\r?\n/;
          }
          break;
        case 2:
          if (typeof matcher === "function") {
            options = mapper;
            mapper = matcher;
            matcher = /\r?\n/;
          } else if (typeof mapper === "object") {
            options = mapper;
            mapper = noop;
          }
      }
      options = Object.assign({}, options);
      options.autoDestroy = true;
      options.transform = transform;
      options.flush = flush;
      options.readableObjectMode = true;
      const stream = new Transform(options);
      stream[kLast] = "";
      stream[kDecoder] = new StringDecoder("utf8");
      stream.matcher = matcher;
      stream.mapper = mapper;
      stream.maxLength = options.maxLength;
      stream.skipOverflow = options.skipOverflow || false;
      stream.overflow = false;
      stream._destroy = function(err, cb) {
        this._writableState.errorEmitted = false;
        cb(err);
      };
      return stream;
    }
    module2.exports = split;
  }
});

// ../packages/logger/lib/ndjsonParse.js
var require_ndjsonParse = __commonJS({
  "../packages/logger/lib/ndjsonParse.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.parse = parse;
    var split2_1 = __importDefault(require_split2());
    var opts = { strict: true };
    function parse() {
      function parseRow(row) {
        try {
          if (row)
            return JSON.parse(row);
        } catch (e) {
          if (opts.strict) {
            this.emit("error", new Error(`Could not parse row "${row.length > 50 ? `${row.slice(0, 50)}...` : row}"`));
          }
        }
      }
      return (0, split2_1.default)(parseRow, opts);
    }
  }
});

// ../packages/logger/lib/streamParser.js
var require_streamParser = __commonJS({
  "../packages/logger/lib/streamParser.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __setModuleDefault = exports2 && exports2.__setModuleDefault || (Object.create ? (function(o, v) {
      Object.defineProperty(o, "default", { enumerable: true, value: v });
    }) : function(o, v) {
      o["default"] = v;
    });
    var __importStar = exports2 && exports2.__importStar || function(mod) {
      if (mod && mod.__esModule) return mod;
      var result = {};
      if (mod != null) {
        for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
      }
      __setModuleDefault(result, mod);
      return result;
    };
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.streamParser = void 0;
    exports2.createStreamParser = createStreamParser;
    var bole_1 = __importDefault(require_bole());
    var ndjson = __importStar(require_ndjsonParse());
    exports2.streamParser = createStreamParser();
    function createStreamParser() {
      const sp = ndjson.parse();
      bole_1.default.output([
        {
          level: "debug",
          stream: sp
        }
      ]);
      return sp;
    }
  }
});

// ../packages/logger/lib/writeToConsole.js
var require_writeToConsole = __commonJS({
  "../packages/logger/lib/writeToConsole.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.writeToConsole = writeToConsole;
    var bole_1 = __importDefault(require_bole());
    function writeToConsole() {
      bole_1.default.output([
        {
          level: "debug",
          stream: process.stdout
        }
      ]);
    }
  }
});

// ../packages/logger/lib/index.js
var require_lib5 = __commonJS({
  "../packages/logger/lib/index.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.writeToConsole = exports2.streamParser = exports2.createStreamParser = exports2.globalWarn = exports2.globalInfo = exports2.logger = void 0;
    var logger_js_1 = require_logger();
    Object.defineProperty(exports2, "logger", { enumerable: true, get: function() {
      return logger_js_1.logger;
    } });
    Object.defineProperty(exports2, "globalInfo", { enumerable: true, get: function() {
      return logger_js_1.globalInfo;
    } });
    Object.defineProperty(exports2, "globalWarn", { enumerable: true, get: function() {
      return logger_js_1.globalWarn;
    } });
    var streamParser_js_1 = require_streamParser();
    Object.defineProperty(exports2, "createStreamParser", { enumerable: true, get: function() {
      return streamParser_js_1.createStreamParser;
    } });
    Object.defineProperty(exports2, "streamParser", { enumerable: true, get: function() {
      return streamParser_js_1.streamParser;
    } });
    var writeToConsole_js_1 = require_writeToConsole();
    Object.defineProperty(exports2, "writeToConsole", { enumerable: true, get: function() {
      return writeToConsole_js_1.writeToConsole;
    } });
  }
});

// ../packages/core-loggers/lib/contextLogger.js
var require_contextLogger = __commonJS({
  "../packages/core-loggers/lib/contextLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.contextLogger = void 0;
    var logger_1 = require_lib5();
    exports2.contextLogger = (0, logger_1.logger)("context");
  }
});

// ../packages/core-loggers/lib/deprecationLogger.js
var require_deprecationLogger = __commonJS({
  "../packages/core-loggers/lib/deprecationLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.deprecationLogger = void 0;
    var logger_1 = require_lib5();
    exports2.deprecationLogger = (0, logger_1.logger)("deprecation");
  }
});

// ../packages/core-loggers/lib/fetchingProgressLogger.js
var require_fetchingProgressLogger = __commonJS({
  "../packages/core-loggers/lib/fetchingProgressLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.fetchingProgressLogger = void 0;
    var logger_1 = require_lib5();
    exports2.fetchingProgressLogger = (0, logger_1.logger)("fetching-progress");
  }
});

// ../packages/core-loggers/lib/hookLogger.js
var require_hookLogger = __commonJS({
  "../packages/core-loggers/lib/hookLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.hookLogger = void 0;
    var logger_1 = require_lib5();
    exports2.hookLogger = (0, logger_1.logger)("hook");
  }
});

// ../packages/core-loggers/lib/installCheckLogger.js
var require_installCheckLogger = __commonJS({
  "../packages/core-loggers/lib/installCheckLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.installCheckLogger = void 0;
    var logger_1 = require_lib5();
    exports2.installCheckLogger = (0, logger_1.logger)("install-check");
  }
});

// ../packages/core-loggers/lib/installingConfigDeps.js
var require_installingConfigDeps = __commonJS({
  "../packages/core-loggers/lib/installingConfigDeps.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.installingConfigDepsLogger = void 0;
    var logger_1 = require_lib5();
    exports2.installingConfigDepsLogger = (0, logger_1.logger)("installing-config-deps");
  }
});

// ../packages/core-loggers/lib/ignoredScriptsLogger.js
var require_ignoredScriptsLogger = __commonJS({
  "../packages/core-loggers/lib/ignoredScriptsLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.ignoredScriptsLogger = void 0;
    var logger_1 = require_lib5();
    exports2.ignoredScriptsLogger = (0, logger_1.logger)("ignored-scripts");
  }
});

// ../packages/core-loggers/lib/lifecycleLogger.js
var require_lifecycleLogger = __commonJS({
  "../packages/core-loggers/lib/lifecycleLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.lifecycleLogger = void 0;
    var logger_1 = require_lib5();
    exports2.lifecycleLogger = (0, logger_1.logger)("lifecycle");
  }
});

// ../packages/core-loggers/lib/linkLogger.js
var require_linkLogger = __commonJS({
  "../packages/core-loggers/lib/linkLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.linkLogger = void 0;
    var logger_1 = require_lib5();
    exports2.linkLogger = (0, logger_1.logger)("link");
  }
});

// ../packages/core-loggers/lib/packageImportMethodLogger.js
var require_packageImportMethodLogger = __commonJS({
  "../packages/core-loggers/lib/packageImportMethodLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.packageImportMethodLogger = void 0;
    var logger_1 = require_lib5();
    exports2.packageImportMethodLogger = (0, logger_1.logger)("package-import-method");
  }
});

// ../packages/core-loggers/lib/packageManifestLogger.js
var require_packageManifestLogger = __commonJS({
  "../packages/core-loggers/lib/packageManifestLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.packageManifestLogger = void 0;
    var logger_1 = require_lib5();
    exports2.packageManifestLogger = (0, logger_1.logger)("package-manifest");
  }
});

// ../packages/core-loggers/lib/peerDependencyIssues.js
var require_peerDependencyIssues = __commonJS({
  "../packages/core-loggers/lib/peerDependencyIssues.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.peerDependencyIssuesLogger = void 0;
    var logger_1 = require_lib5();
    exports2.peerDependencyIssuesLogger = (0, logger_1.logger)("peer-dependency-issues");
  }
});

// ../packages/core-loggers/lib/progressLogger.js
var require_progressLogger = __commonJS({
  "../packages/core-loggers/lib/progressLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.progressLogger = void 0;
    var logger_1 = require_lib5();
    exports2.progressLogger = (0, logger_1.logger)("progress");
  }
});

// ../packages/core-loggers/lib/registryLogger.js
var require_registryLogger = __commonJS({
  "../packages/core-loggers/lib/registryLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
  }
});

// ../packages/core-loggers/lib/removalLogger.js
var require_removalLogger = __commonJS({
  "../packages/core-loggers/lib/removalLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.removalLogger = void 0;
    var logger_1 = require_lib5();
    exports2.removalLogger = (0, logger_1.logger)("removal");
  }
});

// ../packages/core-loggers/lib/requestRetryLogger.js
var require_requestRetryLogger = __commonJS({
  "../packages/core-loggers/lib/requestRetryLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.requestRetryLogger = void 0;
    var logger_1 = require_lib5();
    exports2.requestRetryLogger = (0, logger_1.logger)("request-retry");
  }
});

// ../packages/core-loggers/lib/rootLogger.js
var require_rootLogger = __commonJS({
  "../packages/core-loggers/lib/rootLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.rootLogger = void 0;
    var logger_1 = require_lib5();
    exports2.rootLogger = (0, logger_1.logger)("root");
  }
});

// ../packages/core-loggers/lib/scopeLogger.js
var require_scopeLogger = __commonJS({
  "../packages/core-loggers/lib/scopeLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.scopeLogger = void 0;
    var logger_1 = require_lib5();
    exports2.scopeLogger = (0, logger_1.logger)("scope");
  }
});

// ../packages/core-loggers/lib/skippedOptionalDependencyLogger.js
var require_skippedOptionalDependencyLogger = __commonJS({
  "../packages/core-loggers/lib/skippedOptionalDependencyLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.skippedOptionalDependencyLogger = void 0;
    var logger_1 = require_lib5();
    exports2.skippedOptionalDependencyLogger = (0, logger_1.logger)("skipped-optional-dependency");
  }
});

// ../packages/core-loggers/lib/stageLogger.js
var require_stageLogger = __commonJS({
  "../packages/core-loggers/lib/stageLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.stageLogger = void 0;
    var logger_1 = require_lib5();
    exports2.stageLogger = (0, logger_1.logger)("stage");
  }
});

// ../packages/core-loggers/lib/statsLogger.js
var require_statsLogger = __commonJS({
  "../packages/core-loggers/lib/statsLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.statsLogger = void 0;
    var logger_1 = require_lib5();
    exports2.statsLogger = (0, logger_1.logger)("stats");
  }
});

// ../packages/core-loggers/lib/summaryLogger.js
var require_summaryLogger = __commonJS({
  "../packages/core-loggers/lib/summaryLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.summaryLogger = void 0;
    var logger_1 = require_lib5();
    exports2.summaryLogger = (0, logger_1.logger)("summary");
  }
});

// ../packages/core-loggers/lib/updateCheckLogger.js
var require_updateCheckLogger = __commonJS({
  "../packages/core-loggers/lib/updateCheckLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.updateCheckLogger = void 0;
    var logger_1 = require_lib5();
    exports2.updateCheckLogger = (0, logger_1.logger)("update-check");
  }
});

// ../packages/core-loggers/lib/executionTimeLogger.js
var require_executionTimeLogger = __commonJS({
  "../packages/core-loggers/lib/executionTimeLogger.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.executionTimeLogger = void 0;
    var logger_1 = require_lib5();
    exports2.executionTimeLogger = (0, logger_1.logger)("execution-time");
  }
});

// ../packages/core-loggers/lib/all.js
var require_all = __commonJS({
  "../packages/core-loggers/lib/all.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __exportStar = exports2 && exports2.__exportStar || function(m, exports3) {
      for (var p in m) if (p !== "default" && !Object.prototype.hasOwnProperty.call(exports3, p)) __createBinding(exports3, m, p);
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    __exportStar(require_contextLogger(), exports2);
    __exportStar(require_deprecationLogger(), exports2);
    __exportStar(require_fetchingProgressLogger(), exports2);
    __exportStar(require_hookLogger(), exports2);
    __exportStar(require_installCheckLogger(), exports2);
    __exportStar(require_installingConfigDeps(), exports2);
    __exportStar(require_ignoredScriptsLogger(), exports2);
    __exportStar(require_lifecycleLogger(), exports2);
    __exportStar(require_linkLogger(), exports2);
    __exportStar(require_packageImportMethodLogger(), exports2);
    __exportStar(require_packageManifestLogger(), exports2);
    __exportStar(require_peerDependencyIssues(), exports2);
    __exportStar(require_progressLogger(), exports2);
    __exportStar(require_registryLogger(), exports2);
    __exportStar(require_removalLogger(), exports2);
    __exportStar(require_requestRetryLogger(), exports2);
    __exportStar(require_rootLogger(), exports2);
    __exportStar(require_scopeLogger(), exports2);
    __exportStar(require_skippedOptionalDependencyLogger(), exports2);
    __exportStar(require_stageLogger(), exports2);
    __exportStar(require_statsLogger(), exports2);
    __exportStar(require_summaryLogger(), exports2);
    __exportStar(require_updateCheckLogger(), exports2);
    __exportStar(require_executionTimeLogger(), exports2);
  }
});

// ../packages/core-loggers/lib/index.js
var require_lib6 = __commonJS({
  "../packages/core-loggers/lib/index.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __exportStar = exports2 && exports2.__exportStar || function(m, exports3) {
      for (var p in m) if (p !== "default" && !Object.prototype.hasOwnProperty.call(exports3, p)) __createBinding(exports3, m, p);
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    __exportStar(require_all(), exports2);
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/fs/index.js
var require_fs2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/fs/index.js"(exports2) {
    "use strict";
    var u = require_universalify().fromCallback;
    var fs = require_graceful_fs();
    var api = [
      "access",
      "appendFile",
      "chmod",
      "chown",
      "close",
      "copyFile",
      "cp",
      "fchmod",
      "fchown",
      "fdatasync",
      "fstat",
      "fsync",
      "ftruncate",
      "futimes",
      "glob",
      "lchmod",
      "lchown",
      "lutimes",
      "link",
      "lstat",
      "mkdir",
      "mkdtemp",
      "open",
      "opendir",
      "readdir",
      "readFile",
      "readlink",
      "realpath",
      "rename",
      "rm",
      "rmdir",
      "stat",
      "statfs",
      "symlink",
      "truncate",
      "unlink",
      "utimes",
      "writeFile"
    ].filter((key) => {
      return typeof fs[key] === "function";
    });
    Object.assign(exports2, fs);
    api.forEach((method) => {
      exports2[method] = u(fs[method]);
    });
    exports2.exists = function(filename, callback) {
      if (typeof callback === "function") {
        return fs.exists(filename, callback);
      }
      return new Promise((resolve) => {
        return fs.exists(filename, resolve);
      });
    };
    exports2.read = function(fd, buffer, offset, length, position, callback) {
      if (typeof callback === "function") {
        return fs.read(fd, buffer, offset, length, position, callback);
      }
      return new Promise((resolve, reject) => {
        fs.read(fd, buffer, offset, length, position, (err, bytesRead, buffer2) => {
          if (err) return reject(err);
          resolve({ bytesRead, buffer: buffer2 });
        });
      });
    };
    exports2.write = function(fd, buffer, ...args) {
      if (typeof args[args.length - 1] === "function") {
        return fs.write(fd, buffer, ...args);
      }
      return new Promise((resolve, reject) => {
        fs.write(fd, buffer, ...args, (err, bytesWritten, buffer2) => {
          if (err) return reject(err);
          resolve({ bytesWritten, buffer: buffer2 });
        });
      });
    };
    exports2.readv = function(fd, buffers, ...args) {
      if (typeof args[args.length - 1] === "function") {
        return fs.readv(fd, buffers, ...args);
      }
      return new Promise((resolve, reject) => {
        fs.readv(fd, buffers, ...args, (err, bytesRead, buffers2) => {
          if (err) return reject(err);
          resolve({ bytesRead, buffers: buffers2 });
        });
      });
    };
    exports2.writev = function(fd, buffers, ...args) {
      if (typeof args[args.length - 1] === "function") {
        return fs.writev(fd, buffers, ...args);
      }
      return new Promise((resolve, reject) => {
        fs.writev(fd, buffers, ...args, (err, bytesWritten, buffers2) => {
          if (err) return reject(err);
          resolve({ bytesWritten, buffers: buffers2 });
        });
      });
    };
    if (typeof fs.realpath.native === "function") {
      exports2.realpath.native = u(fs.realpath.native);
    } else {
      process.emitWarning(
        "fs.realpath.native is not a function. Is fs being monkey-patched?",
        "Warning",
        "fs-extra-WARN0003"
      );
    }
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/mkdirs/utils.js
var require_utils3 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/mkdirs/utils.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    module2.exports.checkPath = function checkPath(pth) {
      if (process.platform === "win32") {
        const pathHasInvalidWinCharacters = /[<>:"|?*]/.test(pth.replace(path.parse(pth).root, ""));
        if (pathHasInvalidWinCharacters) {
          const error = new Error(`Path contains invalid characters: ${pth}`);
          error.code = "EINVAL";
          throw error;
        }
      }
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/mkdirs/make-dir.js
var require_make_dir2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/mkdirs/make-dir.js"(exports2, module2) {
    "use strict";
    var fs = require_fs2();
    var { checkPath } = require_utils3();
    var getMode = (options) => {
      const defaults = { mode: 511 };
      if (typeof options === "number") return options;
      return { ...defaults, ...options }.mode;
    };
    module2.exports.makeDir = async (dir, options) => {
      checkPath(dir);
      return fs.mkdir(dir, {
        mode: getMode(options),
        recursive: true
      });
    };
    module2.exports.makeDirSync = (dir, options) => {
      checkPath(dir);
      return fs.mkdirSync(dir, {
        mode: getMode(options),
        recursive: true
      });
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/mkdirs/index.js
var require_mkdirs2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/mkdirs/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var { makeDir: _makeDir, makeDirSync } = require_make_dir2();
    var makeDir = u(_makeDir);
    module2.exports = {
      mkdirs: makeDir,
      mkdirsSync: makeDirSync,
      // alias
      mkdirp: makeDir,
      mkdirpSync: makeDirSync,
      ensureDir: makeDir,
      ensureDirSync: makeDirSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/path-exists/index.js
var require_path_exists2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/path-exists/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var fs = require_fs2();
    function pathExists(path) {
      return fs.access(path).then(() => true).catch(() => false);
    }
    module2.exports = {
      pathExists: u(pathExists),
      pathExistsSync: fs.existsSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/util/utimes.js
var require_utimes2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/util/utimes.js"(exports2, module2) {
    "use strict";
    var fs = require_fs2();
    var u = require_universalify().fromPromise;
    async function utimesMillis(path, atime, mtime) {
      const fd = await fs.open(path, "r+");
      let closeErr = null;
      try {
        await fs.futimes(fd, atime, mtime);
      } finally {
        try {
          await fs.close(fd);
        } catch (e) {
          closeErr = e;
        }
      }
      if (closeErr) {
        throw closeErr;
      }
    }
    function utimesMillisSync(path, atime, mtime) {
      const fd = fs.openSync(path, "r+");
      fs.futimesSync(fd, atime, mtime);
      return fs.closeSync(fd);
    }
    module2.exports = {
      utimesMillis: u(utimesMillis),
      utimesMillisSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/util/stat.js
var require_stat2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/util/stat.js"(exports2, module2) {
    "use strict";
    var fs = require_fs2();
    var path = require("path");
    var u = require_universalify().fromPromise;
    function getStats(src, dest, opts) {
      const statFunc = opts.dereference ? (file) => fs.stat(file, { bigint: true }) : (file) => fs.lstat(file, { bigint: true });
      return Promise.all([
        statFunc(src),
        statFunc(dest).catch((err) => {
          if (err.code === "ENOENT") return null;
          throw err;
        })
      ]).then(([srcStat, destStat]) => ({ srcStat, destStat }));
    }
    function getStatsSync(src, dest, opts) {
      let destStat;
      const statFunc = opts.dereference ? (file) => fs.statSync(file, { bigint: true }) : (file) => fs.lstatSync(file, { bigint: true });
      const srcStat = statFunc(src);
      try {
        destStat = statFunc(dest);
      } catch (err) {
        if (err.code === "ENOENT") return { srcStat, destStat: null };
        throw err;
      }
      return { srcStat, destStat };
    }
    async function checkPaths(src, dest, funcName, opts) {
      const { srcStat, destStat } = await getStats(src, dest, opts);
      if (destStat) {
        if (areIdentical(srcStat, destStat)) {
          const srcBaseName = path.basename(src);
          const destBaseName = path.basename(dest);
          if (funcName === "move" && srcBaseName !== destBaseName && srcBaseName.toLowerCase() === destBaseName.toLowerCase()) {
            return { srcStat, destStat, isChangingCase: true };
          }
          throw new Error("Source and destination must not be the same.");
        }
        if (srcStat.isDirectory() && !destStat.isDirectory()) {
          throw new Error(`Cannot overwrite non-directory '${dest}' with directory '${src}'.`);
        }
        if (!srcStat.isDirectory() && destStat.isDirectory()) {
          throw new Error(`Cannot overwrite directory '${dest}' with non-directory '${src}'.`);
        }
      }
      if (srcStat.isDirectory() && isSrcSubdir(src, dest)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return { srcStat, destStat };
    }
    function checkPathsSync(src, dest, funcName, opts) {
      const { srcStat, destStat } = getStatsSync(src, dest, opts);
      if (destStat) {
        if (areIdentical(srcStat, destStat)) {
          const srcBaseName = path.basename(src);
          const destBaseName = path.basename(dest);
          if (funcName === "move" && srcBaseName !== destBaseName && srcBaseName.toLowerCase() === destBaseName.toLowerCase()) {
            return { srcStat, destStat, isChangingCase: true };
          }
          throw new Error("Source and destination must not be the same.");
        }
        if (srcStat.isDirectory() && !destStat.isDirectory()) {
          throw new Error(`Cannot overwrite non-directory '${dest}' with directory '${src}'.`);
        }
        if (!srcStat.isDirectory() && destStat.isDirectory()) {
          throw new Error(`Cannot overwrite directory '${dest}' with non-directory '${src}'.`);
        }
      }
      if (srcStat.isDirectory() && isSrcSubdir(src, dest)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return { srcStat, destStat };
    }
    async function checkParentPaths(src, srcStat, dest, funcName) {
      const srcParent = path.resolve(path.dirname(src));
      const destParent = path.resolve(path.dirname(dest));
      if (destParent === srcParent || destParent === path.parse(destParent).root) return;
      let destStat;
      try {
        destStat = await fs.stat(destParent, { bigint: true });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
      if (areIdentical(srcStat, destStat)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return checkParentPaths(src, srcStat, destParent, funcName);
    }
    function checkParentPathsSync(src, srcStat, dest, funcName) {
      const srcParent = path.resolve(path.dirname(src));
      const destParent = path.resolve(path.dirname(dest));
      if (destParent === srcParent || destParent === path.parse(destParent).root) return;
      let destStat;
      try {
        destStat = fs.statSync(destParent, { bigint: true });
      } catch (err) {
        if (err.code === "ENOENT") return;
        throw err;
      }
      if (areIdentical(srcStat, destStat)) {
        throw new Error(errMsg(src, dest, funcName));
      }
      return checkParentPathsSync(src, srcStat, destParent, funcName);
    }
    function areIdentical(srcStat, destStat) {
      return destStat.ino !== void 0 && destStat.dev !== void 0 && destStat.ino === srcStat.ino && destStat.dev === srcStat.dev;
    }
    function isSrcSubdir(src, dest) {
      const srcArr = path.resolve(src).split(path.sep).filter((i) => i);
      const destArr = path.resolve(dest).split(path.sep).filter((i) => i);
      return srcArr.every((cur, i) => destArr[i] === cur);
    }
    function errMsg(src, dest, funcName) {
      return `Cannot ${funcName} '${src}' to a subdirectory of itself, '${dest}'.`;
    }
    module2.exports = {
      // checkPaths
      checkPaths: u(checkPaths),
      checkPathsSync,
      // checkParent
      checkParentPaths: u(checkParentPaths),
      checkParentPathsSync,
      // Misc
      isSrcSubdir,
      areIdentical
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/util/async.js
var require_async = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/util/async.js"(exports2, module2) {
    "use strict";
    async function asyncIteratorConcurrentProcess(iterator, fn) {
      const promises = [];
      for await (const item of iterator) {
        promises.push(
          fn(item).then(
            () => null,
            (err) => err ?? new Error("unknown error")
          )
        );
      }
      await Promise.all(
        promises.map(
          (promise) => promise.then((possibleErr) => {
            if (possibleErr !== null) throw possibleErr;
          })
        )
      );
    }
    module2.exports = {
      asyncIteratorConcurrentProcess
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/copy/copy.js
var require_copy3 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/copy/copy.js"(exports2, module2) {
    "use strict";
    var fs = require_fs2();
    var path = require("path");
    var { mkdirs } = require_mkdirs2();
    var { pathExists } = require_path_exists2();
    var { utimesMillis } = require_utimes2();
    var stat = require_stat2();
    var { asyncIteratorConcurrentProcess } = require_async();
    async function copy(src, dest, opts = {}) {
      if (typeof opts === "function") {
        opts = { filter: opts };
      }
      opts.clobber = "clobber" in opts ? !!opts.clobber : true;
      opts.overwrite = "overwrite" in opts ? !!opts.overwrite : opts.clobber;
      if (opts.preserveTimestamps && process.arch === "ia32") {
        process.emitWarning(
          "Using the preserveTimestamps option in 32-bit node is not recommended;\n\n	see https://github.com/jprichardson/node-fs-extra/issues/269",
          "Warning",
          "fs-extra-WARN0001"
        );
      }
      const { srcStat, destStat } = await stat.checkPaths(src, dest, "copy", opts);
      await stat.checkParentPaths(src, srcStat, dest, "copy");
      const include = await runFilter(src, dest, opts);
      if (!include) return;
      const destParent = path.dirname(dest);
      const dirExists = await pathExists(destParent);
      if (!dirExists) {
        await mkdirs(destParent);
      }
      await getStatsAndPerformCopy(destStat, src, dest, opts);
    }
    async function runFilter(src, dest, opts) {
      if (!opts.filter) return true;
      return opts.filter(src, dest);
    }
    async function getStatsAndPerformCopy(destStat, src, dest, opts) {
      const statFn = opts.dereference ? fs.stat : fs.lstat;
      const srcStat = await statFn(src);
      if (srcStat.isDirectory()) return onDir(srcStat, destStat, src, dest, opts);
      if (srcStat.isFile() || srcStat.isCharacterDevice() || srcStat.isBlockDevice()) return onFile(srcStat, destStat, src, dest, opts);
      if (srcStat.isSymbolicLink()) return onLink(destStat, src, dest, opts);
      if (srcStat.isSocket()) throw new Error(`Cannot copy a socket file: ${src}`);
      if (srcStat.isFIFO()) throw new Error(`Cannot copy a FIFO pipe: ${src}`);
      throw new Error(`Unknown file: ${src}`);
    }
    async function onFile(srcStat, destStat, src, dest, opts) {
      if (!destStat) return copyFile(srcStat, src, dest, opts);
      if (opts.overwrite) {
        await fs.unlink(dest);
        return copyFile(srcStat, src, dest, opts);
      }
      if (opts.errorOnExist) {
        throw new Error(`'${dest}' already exists`);
      }
    }
    async function copyFile(srcStat, src, dest, opts) {
      await fs.copyFile(src, dest);
      if (opts.preserveTimestamps) {
        if (fileIsNotWritable(srcStat.mode)) {
          await makeFileWritable(dest, srcStat.mode);
        }
        const updatedSrcStat = await fs.stat(src);
        await utimesMillis(dest, updatedSrcStat.atime, updatedSrcStat.mtime);
      }
      return fs.chmod(dest, srcStat.mode);
    }
    function fileIsNotWritable(srcMode) {
      return (srcMode & 128) === 0;
    }
    function makeFileWritable(dest, srcMode) {
      return fs.chmod(dest, srcMode | 128);
    }
    async function onDir(srcStat, destStat, src, dest, opts) {
      if (!destStat) {
        await fs.mkdir(dest);
      }
      await asyncIteratorConcurrentProcess(await fs.opendir(src), async (item) => {
        const srcItem = path.join(src, item.name);
        const destItem = path.join(dest, item.name);
        const include = await runFilter(srcItem, destItem, opts);
        if (include) {
          const { destStat: destStat2 } = await stat.checkPaths(srcItem, destItem, "copy", opts);
          await getStatsAndPerformCopy(destStat2, srcItem, destItem, opts);
        }
      });
      if (!destStat) {
        await fs.chmod(dest, srcStat.mode);
      }
    }
    async function onLink(destStat, src, dest, opts) {
      let resolvedSrc = await fs.readlink(src);
      if (opts.dereference) {
        resolvedSrc = path.resolve(process.cwd(), resolvedSrc);
      }
      if (!destStat) {
        return fs.symlink(resolvedSrc, dest);
      }
      let resolvedDest = null;
      try {
        resolvedDest = await fs.readlink(dest);
      } catch (e) {
        if (e.code === "EINVAL" || e.code === "UNKNOWN") return fs.symlink(resolvedSrc, dest);
        throw e;
      }
      if (opts.dereference) {
        resolvedDest = path.resolve(process.cwd(), resolvedDest);
      }
      if (resolvedSrc !== resolvedDest) {
        if (stat.isSrcSubdir(resolvedSrc, resolvedDest)) {
          throw new Error(`Cannot copy '${resolvedSrc}' to a subdirectory of itself, '${resolvedDest}'.`);
        }
        if (stat.isSrcSubdir(resolvedDest, resolvedSrc)) {
          throw new Error(`Cannot overwrite '${resolvedDest}' with '${resolvedSrc}'.`);
        }
      }
      await fs.unlink(dest);
      return fs.symlink(resolvedSrc, dest);
    }
    module2.exports = copy;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/copy/copy-sync.js
var require_copy_sync2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/copy/copy-sync.js"(exports2, module2) {
    "use strict";
    var fs = require_graceful_fs();
    var path = require("path");
    var mkdirsSync = require_mkdirs2().mkdirsSync;
    var utimesMillisSync = require_utimes2().utimesMillisSync;
    var stat = require_stat2();
    function copySync(src, dest, opts) {
      if (typeof opts === "function") {
        opts = { filter: opts };
      }
      opts = opts || {};
      opts.clobber = "clobber" in opts ? !!opts.clobber : true;
      opts.overwrite = "overwrite" in opts ? !!opts.overwrite : opts.clobber;
      if (opts.preserveTimestamps && process.arch === "ia32") {
        process.emitWarning(
          "Using the preserveTimestamps option in 32-bit node is not recommended;\n\n	see https://github.com/jprichardson/node-fs-extra/issues/269",
          "Warning",
          "fs-extra-WARN0002"
        );
      }
      const { srcStat, destStat } = stat.checkPathsSync(src, dest, "copy", opts);
      stat.checkParentPathsSync(src, srcStat, dest, "copy");
      if (opts.filter && !opts.filter(src, dest)) return;
      const destParent = path.dirname(dest);
      if (!fs.existsSync(destParent)) mkdirsSync(destParent);
      return getStats(destStat, src, dest, opts);
    }
    function getStats(destStat, src, dest, opts) {
      const statSync = opts.dereference ? fs.statSync : fs.lstatSync;
      const srcStat = statSync(src);
      if (srcStat.isDirectory()) return onDir(srcStat, destStat, src, dest, opts);
      else if (srcStat.isFile() || srcStat.isCharacterDevice() || srcStat.isBlockDevice()) return onFile(srcStat, destStat, src, dest, opts);
      else if (srcStat.isSymbolicLink()) return onLink(destStat, src, dest, opts);
      else if (srcStat.isSocket()) throw new Error(`Cannot copy a socket file: ${src}`);
      else if (srcStat.isFIFO()) throw new Error(`Cannot copy a FIFO pipe: ${src}`);
      throw new Error(`Unknown file: ${src}`);
    }
    function onFile(srcStat, destStat, src, dest, opts) {
      if (!destStat) return copyFile(srcStat, src, dest, opts);
      return mayCopyFile(srcStat, src, dest, opts);
    }
    function mayCopyFile(srcStat, src, dest, opts) {
      if (opts.overwrite) {
        fs.unlinkSync(dest);
        return copyFile(srcStat, src, dest, opts);
      } else if (opts.errorOnExist) {
        throw new Error(`'${dest}' already exists`);
      }
    }
    function copyFile(srcStat, src, dest, opts) {
      fs.copyFileSync(src, dest);
      if (opts.preserveTimestamps) handleTimestamps(srcStat.mode, src, dest);
      return setDestMode(dest, srcStat.mode);
    }
    function handleTimestamps(srcMode, src, dest) {
      if (fileIsNotWritable(srcMode)) makeFileWritable(dest, srcMode);
      return setDestTimestamps(src, dest);
    }
    function fileIsNotWritable(srcMode) {
      return (srcMode & 128) === 0;
    }
    function makeFileWritable(dest, srcMode) {
      return setDestMode(dest, srcMode | 128);
    }
    function setDestMode(dest, srcMode) {
      return fs.chmodSync(dest, srcMode);
    }
    function setDestTimestamps(src, dest) {
      const updatedSrcStat = fs.statSync(src);
      return utimesMillisSync(dest, updatedSrcStat.atime, updatedSrcStat.mtime);
    }
    function onDir(srcStat, destStat, src, dest, opts) {
      if (!destStat) return mkDirAndCopy(srcStat.mode, src, dest, opts);
      return copyDir(src, dest, opts);
    }
    function mkDirAndCopy(srcMode, src, dest, opts) {
      fs.mkdirSync(dest);
      copyDir(src, dest, opts);
      return setDestMode(dest, srcMode);
    }
    function copyDir(src, dest, opts) {
      const dir = fs.opendirSync(src);
      try {
        let dirent;
        while ((dirent = dir.readSync()) !== null) {
          copyDirItem(dirent.name, src, dest, opts);
        }
      } finally {
        dir.closeSync();
      }
    }
    function copyDirItem(item, src, dest, opts) {
      const srcItem = path.join(src, item);
      const destItem = path.join(dest, item);
      if (opts.filter && !opts.filter(srcItem, destItem)) return;
      const { destStat } = stat.checkPathsSync(srcItem, destItem, "copy", opts);
      return getStats(destStat, srcItem, destItem, opts);
    }
    function onLink(destStat, src, dest, opts) {
      let resolvedSrc = fs.readlinkSync(src);
      if (opts.dereference) {
        resolvedSrc = path.resolve(process.cwd(), resolvedSrc);
      }
      if (!destStat) {
        return fs.symlinkSync(resolvedSrc, dest);
      } else {
        let resolvedDest;
        try {
          resolvedDest = fs.readlinkSync(dest);
        } catch (err) {
          if (err.code === "EINVAL" || err.code === "UNKNOWN") return fs.symlinkSync(resolvedSrc, dest);
          throw err;
        }
        if (opts.dereference) {
          resolvedDest = path.resolve(process.cwd(), resolvedDest);
        }
        if (resolvedSrc !== resolvedDest) {
          if (stat.isSrcSubdir(resolvedSrc, resolvedDest)) {
            throw new Error(`Cannot copy '${resolvedSrc}' to a subdirectory of itself, '${resolvedDest}'.`);
          }
          if (stat.isSrcSubdir(resolvedDest, resolvedSrc)) {
            throw new Error(`Cannot overwrite '${resolvedDest}' with '${resolvedSrc}'.`);
          }
        }
        return copyLink(resolvedSrc, dest);
      }
    }
    function copyLink(resolvedSrc, dest) {
      fs.unlinkSync(dest);
      return fs.symlinkSync(resolvedSrc, dest);
    }
    module2.exports = copySync;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/copy/index.js
var require_copy4 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/copy/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    module2.exports = {
      copy: u(require_copy3()),
      copySync: require_copy_sync2()
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/remove/index.js
var require_remove2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/remove/index.js"(exports2, module2) {
    "use strict";
    var fs = require_graceful_fs();
    var u = require_universalify().fromCallback;
    function remove(path, callback) {
      fs.rm(path, { recursive: true, force: true }, callback);
    }
    function removeSync(path) {
      fs.rmSync(path, { recursive: true, force: true });
    }
    module2.exports = {
      remove: u(remove),
      removeSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/empty/index.js
var require_empty2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/empty/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var fs = require_fs2();
    var path = require("path");
    var mkdir = require_mkdirs2();
    var remove = require_remove2();
    var emptyDir = u(async function emptyDir2(dir) {
      let items;
      try {
        items = await fs.readdir(dir);
      } catch {
        return mkdir.mkdirs(dir);
      }
      return Promise.all(items.map((item) => remove.remove(path.join(dir, item))));
    });
    function emptyDirSync(dir) {
      let items;
      try {
        items = fs.readdirSync(dir);
      } catch {
        return mkdir.mkdirsSync(dir);
      }
      items.forEach((item) => {
        item = path.join(dir, item);
        remove.removeSync(item);
      });
    }
    module2.exports = {
      emptyDirSync,
      emptydirSync: emptyDirSync,
      emptyDir,
      emptydir: emptyDir
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/file.js
var require_file2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/file.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var path = require("path");
    var fs = require_fs2();
    var mkdir = require_mkdirs2();
    async function createFile(file) {
      let stats;
      try {
        stats = await fs.stat(file);
      } catch {
      }
      if (stats && stats.isFile()) return;
      const dir = path.dirname(file);
      let dirStats = null;
      try {
        dirStats = await fs.stat(dir);
      } catch (err) {
        if (err.code === "ENOENT") {
          await mkdir.mkdirs(dir);
          await fs.writeFile(file, "");
          return;
        } else {
          throw err;
        }
      }
      if (dirStats.isDirectory()) {
        await fs.writeFile(file, "");
      } else {
        await fs.readdir(dir);
      }
    }
    function createFileSync(file) {
      let stats;
      try {
        stats = fs.statSync(file);
      } catch {
      }
      if (stats && stats.isFile()) return;
      const dir = path.dirname(file);
      try {
        if (!fs.statSync(dir).isDirectory()) {
          fs.readdirSync(dir);
        }
      } catch (err) {
        if (err && err.code === "ENOENT") mkdir.mkdirsSync(dir);
        else throw err;
      }
      fs.writeFileSync(file, "");
    }
    module2.exports = {
      createFile: u(createFile),
      createFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/link.js
var require_link2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/link.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var path = require("path");
    var fs = require_fs2();
    var mkdir = require_mkdirs2();
    var { pathExists } = require_path_exists2();
    var { areIdentical } = require_stat2();
    async function createLink(srcpath, dstpath) {
      let dstStat;
      try {
        dstStat = await fs.lstat(dstpath);
      } catch {
      }
      let srcStat;
      try {
        srcStat = await fs.lstat(srcpath);
      } catch (err) {
        err.message = err.message.replace("lstat", "ensureLink");
        throw err;
      }
      if (dstStat && areIdentical(srcStat, dstStat)) return;
      const dir = path.dirname(dstpath);
      const dirExists = await pathExists(dir);
      if (!dirExists) {
        await mkdir.mkdirs(dir);
      }
      await fs.link(srcpath, dstpath);
    }
    function createLinkSync(srcpath, dstpath) {
      let dstStat;
      try {
        dstStat = fs.lstatSync(dstpath);
      } catch {
      }
      try {
        const srcStat = fs.lstatSync(srcpath);
        if (dstStat && areIdentical(srcStat, dstStat)) return;
      } catch (err) {
        err.message = err.message.replace("lstat", "ensureLink");
        throw err;
      }
      const dir = path.dirname(dstpath);
      const dirExists = fs.existsSync(dir);
      if (dirExists) return fs.linkSync(srcpath, dstpath);
      mkdir.mkdirsSync(dir);
      return fs.linkSync(srcpath, dstpath);
    }
    module2.exports = {
      createLink: u(createLink),
      createLinkSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/symlink-paths.js
var require_symlink_paths2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/symlink-paths.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    var fs = require_fs2();
    var { pathExists } = require_path_exists2();
    var u = require_universalify().fromPromise;
    async function symlinkPaths(srcpath, dstpath) {
      if (path.isAbsolute(srcpath)) {
        try {
          await fs.lstat(srcpath);
        } catch (err) {
          err.message = err.message.replace("lstat", "ensureSymlink");
          throw err;
        }
        return {
          toCwd: srcpath,
          toDst: srcpath
        };
      }
      const dstdir = path.dirname(dstpath);
      const relativeToDst = path.join(dstdir, srcpath);
      const exists = await pathExists(relativeToDst);
      if (exists) {
        return {
          toCwd: relativeToDst,
          toDst: srcpath
        };
      }
      try {
        await fs.lstat(srcpath);
      } catch (err) {
        err.message = err.message.replace("lstat", "ensureSymlink");
        throw err;
      }
      return {
        toCwd: srcpath,
        toDst: path.relative(dstdir, srcpath)
      };
    }
    function symlinkPathsSync(srcpath, dstpath) {
      if (path.isAbsolute(srcpath)) {
        const exists2 = fs.existsSync(srcpath);
        if (!exists2) throw new Error("absolute srcpath does not exist");
        return {
          toCwd: srcpath,
          toDst: srcpath
        };
      }
      const dstdir = path.dirname(dstpath);
      const relativeToDst = path.join(dstdir, srcpath);
      const exists = fs.existsSync(relativeToDst);
      if (exists) {
        return {
          toCwd: relativeToDst,
          toDst: srcpath
        };
      }
      const srcExists = fs.existsSync(srcpath);
      if (!srcExists) throw new Error("relative srcpath does not exist");
      return {
        toCwd: srcpath,
        toDst: path.relative(dstdir, srcpath)
      };
    }
    module2.exports = {
      symlinkPaths: u(symlinkPaths),
      symlinkPathsSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/symlink-type.js
var require_symlink_type2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/symlink-type.js"(exports2, module2) {
    "use strict";
    var fs = require_fs2();
    var u = require_universalify().fromPromise;
    async function symlinkType(srcpath, type) {
      if (type) return type;
      let stats;
      try {
        stats = await fs.lstat(srcpath);
      } catch {
        return "file";
      }
      return stats && stats.isDirectory() ? "dir" : "file";
    }
    function symlinkTypeSync(srcpath, type) {
      if (type) return type;
      let stats;
      try {
        stats = fs.lstatSync(srcpath);
      } catch {
        return "file";
      }
      return stats && stats.isDirectory() ? "dir" : "file";
    }
    module2.exports = {
      symlinkType: u(symlinkType),
      symlinkTypeSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/symlink.js
var require_symlink2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/symlink.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var path = require("path");
    var fs = require_fs2();
    var { mkdirs, mkdirsSync } = require_mkdirs2();
    var { symlinkPaths, symlinkPathsSync } = require_symlink_paths2();
    var { symlinkType, symlinkTypeSync } = require_symlink_type2();
    var { pathExists } = require_path_exists2();
    var { areIdentical } = require_stat2();
    async function createSymlink(srcpath, dstpath, type) {
      let stats;
      try {
        stats = await fs.lstat(dstpath);
      } catch {
      }
      if (stats && stats.isSymbolicLink()) {
        const [srcStat, dstStat] = await Promise.all([
          fs.stat(srcpath),
          fs.stat(dstpath)
        ]);
        if (areIdentical(srcStat, dstStat)) return;
      }
      const relative = await symlinkPaths(srcpath, dstpath);
      srcpath = relative.toDst;
      const toType = await symlinkType(relative.toCwd, type);
      const dir = path.dirname(dstpath);
      if (!await pathExists(dir)) {
        await mkdirs(dir);
      }
      return fs.symlink(srcpath, dstpath, toType);
    }
    function createSymlinkSync(srcpath, dstpath, type) {
      let stats;
      try {
        stats = fs.lstatSync(dstpath);
      } catch {
      }
      if (stats && stats.isSymbolicLink()) {
        const srcStat = fs.statSync(srcpath);
        const dstStat = fs.statSync(dstpath);
        if (areIdentical(srcStat, dstStat)) return;
      }
      const relative = symlinkPathsSync(srcpath, dstpath);
      srcpath = relative.toDst;
      type = symlinkTypeSync(relative.toCwd, type);
      const dir = path.dirname(dstpath);
      const exists = fs.existsSync(dir);
      if (exists) return fs.symlinkSync(srcpath, dstpath, type);
      mkdirsSync(dir);
      return fs.symlinkSync(srcpath, dstpath, type);
    }
    module2.exports = {
      createSymlink: u(createSymlink),
      createSymlinkSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/index.js
var require_ensure2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/ensure/index.js"(exports2, module2) {
    "use strict";
    var { createFile, createFileSync } = require_file2();
    var { createLink, createLinkSync } = require_link2();
    var { createSymlink, createSymlinkSync } = require_symlink2();
    module2.exports = {
      // file
      createFile,
      createFileSync,
      ensureFile: createFile,
      ensureFileSync: createFileSync,
      // link
      createLink,
      createLinkSync,
      ensureLink: createLink,
      ensureLinkSync: createLinkSync,
      // symlink
      createSymlink,
      createSymlinkSync,
      ensureSymlink: createSymlink,
      ensureSymlinkSync: createSymlinkSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/jsonfile.js
var require_jsonfile3 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/jsonfile.js"(exports2, module2) {
    "use strict";
    var jsonFile = require_jsonfile();
    module2.exports = {
      // jsonfile exports
      readJson: jsonFile.readFile,
      readJsonSync: jsonFile.readFileSync,
      writeJson: jsonFile.writeFile,
      writeJsonSync: jsonFile.writeFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/output-file/index.js
var require_output_file2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/output-file/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var fs = require_fs2();
    var path = require("path");
    var mkdir = require_mkdirs2();
    var pathExists = require_path_exists2().pathExists;
    async function outputFile(file, data, encoding = "utf-8") {
      const dir = path.dirname(file);
      if (!await pathExists(dir)) {
        await mkdir.mkdirs(dir);
      }
      return fs.writeFile(file, data, encoding);
    }
    function outputFileSync(file, ...args) {
      const dir = path.dirname(file);
      if (!fs.existsSync(dir)) {
        mkdir.mkdirsSync(dir);
      }
      fs.writeFileSync(file, ...args);
    }
    module2.exports = {
      outputFile: u(outputFile),
      outputFileSync
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/output-json.js
var require_output_json2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/output-json.js"(exports2, module2) {
    "use strict";
    var { stringify } = require_utils2();
    var { outputFile } = require_output_file2();
    async function outputJson(file, data, options = {}) {
      const str = stringify(data, options);
      await outputFile(file, str, options);
    }
    module2.exports = outputJson;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/output-json-sync.js
var require_output_json_sync2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/output-json-sync.js"(exports2, module2) {
    "use strict";
    var { stringify } = require_utils2();
    var { outputFileSync } = require_output_file2();
    function outputJsonSync(file, data, options) {
      const str = stringify(data, options);
      outputFileSync(file, str, options);
    }
    module2.exports = outputJsonSync;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/index.js
var require_json2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/json/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    var jsonFile = require_jsonfile3();
    jsonFile.outputJson = u(require_output_json2());
    jsonFile.outputJsonSync = require_output_json_sync2();
    jsonFile.outputJSON = jsonFile.outputJson;
    jsonFile.outputJSONSync = jsonFile.outputJsonSync;
    jsonFile.writeJSON = jsonFile.writeJson;
    jsonFile.writeJSONSync = jsonFile.writeJsonSync;
    jsonFile.readJSON = jsonFile.readJson;
    jsonFile.readJSONSync = jsonFile.readJsonSync;
    module2.exports = jsonFile;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/move/move.js
var require_move3 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/move/move.js"(exports2, module2) {
    "use strict";
    var fs = require_fs2();
    var path = require("path");
    var { copy } = require_copy4();
    var { remove } = require_remove2();
    var { mkdirp } = require_mkdirs2();
    var { pathExists } = require_path_exists2();
    var stat = require_stat2();
    async function move(src, dest, opts = {}) {
      const overwrite = opts.overwrite || opts.clobber || false;
      const { srcStat, isChangingCase = false } = await stat.checkPaths(src, dest, "move", opts);
      await stat.checkParentPaths(src, srcStat, dest, "move");
      const destParent = path.dirname(dest);
      const parsedParentPath = path.parse(destParent);
      if (parsedParentPath.root !== destParent) {
        await mkdirp(destParent);
      }
      return doRename(src, dest, overwrite, isChangingCase);
    }
    async function doRename(src, dest, overwrite, isChangingCase) {
      if (!isChangingCase) {
        if (overwrite) {
          await remove(dest);
        } else if (await pathExists(dest)) {
          throw new Error("dest already exists.");
        }
      }
      try {
        await fs.rename(src, dest);
      } catch (err) {
        if (err.code !== "EXDEV") {
          throw err;
        }
        await moveAcrossDevice(src, dest, overwrite);
      }
    }
    async function moveAcrossDevice(src, dest, overwrite) {
      const opts = {
        overwrite,
        errorOnExist: true,
        preserveTimestamps: true
      };
      await copy(src, dest, opts);
      return remove(src);
    }
    module2.exports = move;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/move/move-sync.js
var require_move_sync2 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/move/move-sync.js"(exports2, module2) {
    "use strict";
    var fs = require_graceful_fs();
    var path = require("path");
    var copySync = require_copy4().copySync;
    var removeSync = require_remove2().removeSync;
    var mkdirpSync = require_mkdirs2().mkdirpSync;
    var stat = require_stat2();
    function moveSync(src, dest, opts) {
      opts = opts || {};
      const overwrite = opts.overwrite || opts.clobber || false;
      const { srcStat, isChangingCase = false } = stat.checkPathsSync(src, dest, "move", opts);
      stat.checkParentPathsSync(src, srcStat, dest, "move");
      if (!isParentRoot(dest)) mkdirpSync(path.dirname(dest));
      return doRename(src, dest, overwrite, isChangingCase);
    }
    function isParentRoot(dest) {
      const parent = path.dirname(dest);
      const parsedPath = path.parse(parent);
      return parsedPath.root === parent;
    }
    function doRename(src, dest, overwrite, isChangingCase) {
      if (isChangingCase) return rename(src, dest, overwrite);
      if (overwrite) {
        removeSync(dest);
        return rename(src, dest, overwrite);
      }
      if (fs.existsSync(dest)) throw new Error("dest already exists.");
      return rename(src, dest, overwrite);
    }
    function rename(src, dest, overwrite) {
      try {
        fs.renameSync(src, dest);
      } catch (err) {
        if (err.code !== "EXDEV") throw err;
        return moveAcrossDevice(src, dest, overwrite);
      }
    }
    function moveAcrossDevice(src, dest, overwrite) {
      const opts = {
        overwrite,
        errorOnExist: true,
        preserveTimestamps: true
      };
      copySync(src, dest, opts);
      return removeSync(src);
    }
    module2.exports = moveSync;
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/move/index.js
var require_move4 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/move/index.js"(exports2, module2) {
    "use strict";
    var u = require_universalify().fromPromise;
    module2.exports = {
      move: u(require_move3()),
      moveSync: require_move_sync2()
    };
  }
});

// ../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/index.js
var require_lib7 = __commonJS({
  "../node_modules/.pnpm/fs-extra@11.3.3/node_modules/fs-extra/lib/index.js"(exports2, module2) {
    "use strict";
    module2.exports = {
      // Export promiseified graceful-fs:
      ...require_fs2(),
      // Export extra methods:
      ...require_copy4(),
      ...require_empty2(),
      ...require_ensure2(),
      ...require_json2(),
      ...require_mkdirs2(),
      ...require_move4(),
      ...require_output_file2(),
      ...require_path_exists2(),
      ...require_remove2()
    };
  }
});

// ../node_modules/.pnpm/make-empty-dir@3.0.2/node_modules/make-empty-dir/index.js
var require_make_empty_dir = __commonJS({
  "../node_modules/.pnpm/make-empty-dir@3.0.2/node_modules/make-empty-dir/index.js"(exports2, module2) {
    "use strict";
    var fs = require("fs");
    var path = require("path");
    var rimraf = require_rimraf();
    module2.exports = async function makeEmptyDir(dir, opts) {
      if (opts && opts.recursive) {
        await fs.promises.mkdir(path.dirname(dir), { recursive: true });
      }
      try {
        await fs.promises.mkdir(dir);
        return "created";
      } catch (err) {
        if (err.code === "EEXIST") {
          await removeContentsOfDir(dir);
          return "emptied";
        }
        throw err;
      }
    };
    async function removeContentsOfDir(dir) {
      const items = await fs.promises.readdir(dir);
      for (const item of items) {
        await rimraf(path.join(dir, item));
      }
    }
    module2.exports.sync = function makeEmptyDirSync(dir, opts) {
      if (opts && opts.recursive) {
        fs.mkdirSync(path.dirname(dir), { recursive: true });
      }
      try {
        fs.mkdirSync(dir);
        return "created";
      } catch (err) {
        if (err.code === "EEXIST") {
          removeContentsOfDirSync(dir);
          return "emptied";
        }
        throw err;
      }
    };
    function removeContentsOfDirSync(dir) {
      const items = fs.readdirSync(dir);
      for (const item of items) {
        rimraf.sync(path.join(dir, item));
      }
    }
  }
});

// ../node_modules/.pnpm/truncate-utf8-bytes@1.0.2/node_modules/truncate-utf8-bytes/lib/truncate.js
var require_truncate = __commonJS({
  "../node_modules/.pnpm/truncate-utf8-bytes@1.0.2/node_modules/truncate-utf8-bytes/lib/truncate.js"(exports2, module2) {
    "use strict";
    function isHighSurrogate(codePoint) {
      return codePoint >= 55296 && codePoint <= 56319;
    }
    function isLowSurrogate(codePoint) {
      return codePoint >= 56320 && codePoint <= 57343;
    }
    module2.exports = function truncate(getLength, string, byteLength) {
      if (typeof string !== "string") {
        throw new Error("Input must be string");
      }
      var charLength = string.length;
      var curByteLength = 0;
      var codePoint;
      var segment;
      for (var i = 0; i < charLength; i += 1) {
        codePoint = string.charCodeAt(i);
        segment = string[i];
        if (isHighSurrogate(codePoint) && isLowSurrogate(string.charCodeAt(i + 1))) {
          i += 1;
          segment += string[i];
        }
        curByteLength += getLength(segment);
        if (curByteLength === byteLength) {
          return string.slice(0, i + 1);
        } else if (curByteLength > byteLength) {
          return string.slice(0, i - segment.length + 1);
        }
      }
      return string;
    };
  }
});

// ../node_modules/.pnpm/truncate-utf8-bytes@1.0.2/node_modules/truncate-utf8-bytes/index.js
var require_truncate_utf8_bytes = __commonJS({
  "../node_modules/.pnpm/truncate-utf8-bytes@1.0.2/node_modules/truncate-utf8-bytes/index.js"(exports2, module2) {
    "use strict";
    var truncate = require_truncate();
    var getLength = Buffer.byteLength.bind(Buffer);
    module2.exports = truncate.bind(null, getLength);
  }
});

// ../node_modules/.pnpm/sanitize-filename@1.6.3/node_modules/sanitize-filename/index.js
var require_sanitize_filename = __commonJS({
  "../node_modules/.pnpm/sanitize-filename@1.6.3/node_modules/sanitize-filename/index.js"(exports2, module2) {
    "use strict";
    var truncate = require_truncate_utf8_bytes();
    var illegalRe = /[\/\?<>\\:\*\|"]/g;
    var controlRe = /[\x00-\x1f\x80-\x9f]/g;
    var reservedRe = /^\.+$/;
    var windowsReservedRe = /^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$/i;
    var windowsTrailingRe = /[\. ]+$/;
    function sanitize(input, replacement) {
      if (typeof input !== "string") {
        throw new Error("Input must be string");
      }
      var sanitized = input.replace(illegalRe, replacement).replace(controlRe, replacement).replace(reservedRe, replacement).replace(windowsReservedRe, replacement).replace(windowsTrailingRe, replacement);
      return truncate(sanitized, 255);
    }
    module2.exports = function(input, options) {
      var replacement = options && options.replacement || "";
      var output = sanitize(input, replacement);
      if (replacement === "") {
        return output;
      }
      return sanitize(output, "");
    };
  }
});

// ../node_modules/.pnpm/crypto-random-string@2.0.0/node_modules/crypto-random-string/index.js
var require_crypto_random_string = __commonJS({
  "../node_modules/.pnpm/crypto-random-string@2.0.0/node_modules/crypto-random-string/index.js"(exports2, module2) {
    "use strict";
    var crypto = require("crypto");
    module2.exports = (length) => {
      if (!Number.isFinite(length)) {
        throw new TypeError("Expected a finite number");
      }
      return crypto.randomBytes(Math.ceil(length / 2)).toString("hex").slice(0, length);
    };
  }
});

// ../node_modules/.pnpm/unique-string@2.0.0/node_modules/unique-string/index.js
var require_unique_string = __commonJS({
  "../node_modules/.pnpm/unique-string@2.0.0/node_modules/unique-string/index.js"(exports2, module2) {
    "use strict";
    var cryptoRandomString = require_crypto_random_string();
    module2.exports = () => cryptoRandomString(32);
  }
});

// ../node_modules/.pnpm/path-temp@2.1.0/node_modules/path-temp/index.js
var require_path_temp = __commonJS({
  "../node_modules/.pnpm/path-temp@2.1.0/node_modules/path-temp/index.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    var uniqueString = require_unique_string();
    module2.exports = function pathTemp(folder) {
      return path.join(folder, `_tmp_${process.pid}_${uniqueString()}`);
    };
    module2.exports.fastPathTemp = function pathTempFast(file) {
      return path.join(path.dirname(file), `${path.basename(file)}_tmp_${process.pid}`);
    };
  }
});

// ../fs/indexed-pkg-importer/lib/importIndexedDir.js
var require_importIndexedDir = __commonJS({
  "../fs/indexed-pkg-importer/lib/importIndexedDir.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.importIndexedDir = importIndexedDir;
    var fs_1 = __importDefault(require("fs"));
    var util_1 = __importDefault(require("util"));
    var fs_extra_1 = require_lib7();
    var path_1 = __importDefault(require("path"));
    var logger_1 = require_lib5();
    var rimraf_1 = require_rimraf();
    var make_empty_dir_1 = require_make_empty_dir();
    var sanitize_filename_1 = __importDefault(require_sanitize_filename());
    var path_temp_1 = require_path_temp();
    var rename_overwrite_1 = __importDefault(require_rename_overwrite());
    var graceful_fs_1 = __importDefault(require_lib());
    var filenameConflictsLogger = (0, logger_1.logger)("_filename-conflicts");
    function importIndexedDir(importFile, newDir, filenames, opts) {
      const stage = (0, path_temp_1.fastPathTemp)(newDir);
      try {
        tryImportIndexedDir(importFile, stage, filenames);
        if (opts.keepModulesDir) {
          moveOrMergeModulesDirs(path_1.default.join(newDir, "node_modules"), path_1.default.join(stage, "node_modules"));
        }
        rename_overwrite_1.default.sync(stage, newDir);
      } catch (err) {
        try {
          (0, rimraf_1.sync)(stage);
        } catch {
        }
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "EEXIST") {
          const { uniqueFileMap, conflictingFileNames } = getUniqueFileMap(filenames);
          if (Object.keys(conflictingFileNames).length === 0)
            throw err;
          filenameConflictsLogger.debug({
            conflicts: conflictingFileNames,
            writingTo: newDir
          });
          (0, logger_1.globalWarn)(`Not all files were linked to "${path_1.default.relative(process.cwd(), newDir)}". Some of the files have equal names in different case, which is an issue on case-insensitive filesystems. The conflicting file names are: ${JSON.stringify(conflictingFileNames)}`);
          importIndexedDir(importFile, newDir, uniqueFileMap, opts);
          return;
        }
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") {
          const { sanitizedFilenames, invalidFilenames } = sanitizeFilenames(filenames);
          if (invalidFilenames.length === 0)
            throw err;
          (0, logger_1.globalWarn)(`The package linked to "${path_1.default.relative(process.cwd(), newDir)}" had files with invalid names: ${invalidFilenames.join(", ")}. They were renamed.`);
          importIndexedDir(importFile, newDir, sanitizedFilenames, opts);
          return;
        }
        throw err;
      }
    }
    function sanitizeFilenames(filenames) {
      const sanitizedFilenames = {};
      const invalidFilenames = [];
      for (const [filename, src] of Object.entries(filenames)) {
        const sanitizedFilename = filename.split("/").map((f) => (0, sanitize_filename_1.default)(f)).join("/");
        if (sanitizedFilename !== filename) {
          invalidFilenames.push(filename);
        }
        sanitizedFilenames[sanitizedFilename] = src;
      }
      return { sanitizedFilenames, invalidFilenames };
    }
    function tryImportIndexedDir(importFile, newDir, filenames) {
      (0, make_empty_dir_1.sync)(newDir, { recursive: true });
      const allDirs = /* @__PURE__ */ new Set();
      for (const f in filenames) {
        const dir = path_1.default.dirname(f);
        if (dir === ".")
          continue;
        allDirs.add(dir);
      }
      Array.from(allDirs).sort((d1, d2) => d1.length - d2.length).forEach((dir) => fs_1.default.mkdirSync(path_1.default.join(newDir, dir), { recursive: true }));
      for (const [f, src] of Object.entries(filenames)) {
        const dest = path_1.default.join(newDir, f);
        importFile(src, dest);
      }
    }
    function getUniqueFileMap(fileMap) {
      const lowercaseFiles = /* @__PURE__ */ new Map();
      const conflictingFileNames = {};
      const uniqueFileMap = {};
      for (const filename of Object.keys(fileMap).sort()) {
        const lowercaseFilename = filename.toLowerCase();
        if (lowercaseFiles.has(lowercaseFilename)) {
          conflictingFileNames[filename] = lowercaseFiles.get(lowercaseFilename);
          continue;
        }
        lowercaseFiles.set(lowercaseFilename, filename);
        uniqueFileMap[filename] = fileMap[filename];
      }
      return {
        conflictingFileNames,
        uniqueFileMap
      };
    }
    function moveOrMergeModulesDirs(src, dest) {
      try {
        renameEvenAcrossDevices(src, dest);
      } catch (err) {
        switch (util_1.default.types.isNativeError(err) && "code" in err && err.code) {
          case "ENOENT":
            return;
          case "ENOTEMPTY":
          case "EPERM":
            mergeModulesDirs(src, dest);
            return;
          default:
            throw err;
        }
      }
    }
    function renameEvenAcrossDevices(src, dest) {
      try {
        graceful_fs_1.default.renameSync(src, dest);
      } catch (err) {
        if (!(util_1.default.types.isNativeError(err) && "code" in err && err.code === "EXDEV"))
          throw err;
        (0, fs_extra_1.copySync)(src, dest);
      }
    }
    function mergeModulesDirs(src, dest) {
      const srcFiles = fs_1.default.readdirSync(src);
      const destFiles = new Set(fs_1.default.readdirSync(dest));
      const filesToMove = srcFiles.filter((file) => !destFiles.has(file));
      for (const file of filesToMove) {
        renameEvenAcrossDevices(path_1.default.join(src, file), path_1.default.join(dest, file));
      }
    }
  }
});

// ../node_modules/.pnpm/@reflink+reflink@0.1.19/node_modules/@reflink/reflink/binding.js
var require_binding = __commonJS({
  "../node_modules/.pnpm/@reflink+reflink@0.1.19/node_modules/@reflink/reflink/binding.js"(exports2, module2) {
    var { existsSync, readFileSync } = require("fs");
    var { join } = require("path");
    var { platform, arch } = process;
    var nativeBinding = null;
    var localFileExisted = false;
    var loadError = null;
    function isMusl() {
      if (!process.report || typeof process.report.getReport !== "function") {
        try {
          const lddPath = require("child_process").execSync("which ldd").toString().trim();
          return readFileSync(lddPath, "utf8").includes("musl");
        } catch (e) {
          return true;
        }
      } else {
        const { glibcVersionRuntime } = process.report.getReport().header;
        return !glibcVersionRuntime;
      }
    }
    switch (platform) {
      case "android":
        switch (arch) {
          case "arm64":
            localFileExisted = existsSync(join(__dirname, "reflink.android-arm64.node"));
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.android-arm64.node");
              } else {
                nativeBinding = require("@reflink/reflink-android-arm64");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          case "arm":
            localFileExisted = existsSync(join(__dirname, "reflink.android-arm-eabi.node"));
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.android-arm-eabi.node");
              } else {
                nativeBinding = require("@reflink/reflink-android-arm-eabi");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          default:
            throw new Error(`Unsupported architecture on Android ${arch}`);
        }
        break;
      case "win32":
        switch (arch) {
          case "x64":
            localFileExisted = existsSync(
              join(__dirname, "reflink.win32-x64-msvc.node")
            );
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.win32-x64-msvc.node");
              } else {
                nativeBinding = require("./reflink.win32-x64-msvc-J2TZHRQI.node");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          case "ia32":
            localFileExisted = existsSync(
              join(__dirname, "reflink.win32-ia32-msvc.node")
            );
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.win32-ia32-msvc.node");
              } else {
                nativeBinding = require("@reflink/reflink-win32-ia32-msvc");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          case "arm64":
            localFileExisted = existsSync(
              join(__dirname, "reflink.win32-arm64-msvc.node")
            );
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.win32-arm64-msvc.node");
              } else {
                nativeBinding = require("./reflink.win32-arm64-msvc-Q6BARPPB.node");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          default:
            throw new Error(`Unsupported architecture on Windows: ${arch}`);
        }
        break;
      case "darwin":
        localFileExisted = existsSync(join(__dirname, "reflink.darwin-universal.node"));
        try {
          if (localFileExisted) {
            nativeBinding = require("./reflink.darwin-universal.node");
          } else {
            nativeBinding = require("@reflink/reflink-darwin-universal");
          }
          break;
        } catch {
        }
        switch (arch) {
          case "x64":
            localFileExisted = existsSync(join(__dirname, "reflink.darwin-x64.node"));
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.darwin-x64.node");
              } else {
                nativeBinding = require("./reflink.darwin-x64-3G3H6IW4.node");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          case "arm64":
            localFileExisted = existsSync(
              join(__dirname, "reflink.darwin-arm64.node")
            );
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.darwin-arm64.node");
              } else {
                nativeBinding = require("./reflink.darwin-arm64-2HJ4WGO6.node");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          default:
            throw new Error(`Unsupported architecture on macOS: ${arch}`);
        }
        break;
      case "freebsd":
        if (arch !== "x64") {
          throw new Error(`Unsupported architecture on FreeBSD: ${arch}`);
        }
        localFileExisted = existsSync(join(__dirname, "reflink.freebsd-x64.node"));
        try {
          if (localFileExisted) {
            nativeBinding = require("./reflink.freebsd-x64.node");
          } else {
            nativeBinding = require("@reflink/reflink-freebsd-x64");
          }
        } catch (e) {
          loadError = e;
        }
        break;
      case "linux":
        switch (arch) {
          case "x64":
            if (isMusl()) {
              localFileExisted = existsSync(
                join(__dirname, "reflink.linux-x64-musl.node")
              );
              try {
                if (localFileExisted) {
                  nativeBinding = require("./reflink.linux-x64-musl.node");
                } else {
                  nativeBinding = require("@reflink/reflink-linux-x64-musl");
                }
              } catch (e) {
                loadError = e;
              }
            } else {
              localFileExisted = existsSync(
                join(__dirname, "reflink.linux-x64-gnu.node")
              );
              try {
                if (localFileExisted) {
                  nativeBinding = require("./reflink.linux-x64-gnu.node");
                } else {
                  nativeBinding = require("@reflink/reflink-linux-x64-gnu");
                }
              } catch (e) {
                loadError = e;
              }
            }
            break;
          case "arm64":
            if (isMusl()) {
              localFileExisted = existsSync(
                join(__dirname, "reflink.linux-arm64-musl.node")
              );
              try {
                if (localFileExisted) {
                  nativeBinding = require("./reflink.linux-arm64-musl.node");
                } else {
                  nativeBinding = require("@reflink/reflink-linux-arm64-musl");
                }
              } catch (e) {
                loadError = e;
              }
            } else {
              localFileExisted = existsSync(
                join(__dirname, "reflink.linux-arm64-gnu.node")
              );
              try {
                if (localFileExisted) {
                  nativeBinding = require("./reflink.linux-arm64-gnu.node");
                } else {
                  nativeBinding = require("@reflink/reflink-linux-arm64-gnu");
                }
              } catch (e) {
                loadError = e;
              }
            }
            break;
          case "arm":
            localFileExisted = existsSync(
              join(__dirname, "reflink.linux-arm-gnueabihf.node")
            );
            try {
              if (localFileExisted) {
                nativeBinding = require("./reflink.linux-arm-gnueabihf.node");
              } else {
                nativeBinding = require("@reflink/reflink-linux-arm-gnueabihf");
              }
            } catch (e) {
              loadError = e;
            }
            break;
          default:
            throw new Error(`Unsupported architecture on Linux: ${arch}`);
        }
        break;
      default:
        throw new Error(`Unsupported OS: ${platform}, architecture: ${arch}`);
    }
    if (!nativeBinding) {
      if (loadError) {
        throw loadError;
      }
      throw new Error(`Failed to load native binding`);
    }
    var { ReflinkError, reflinkFile, reflinkFileSync } = nativeBinding;
    module2.exports.ReflinkError = ReflinkError;
    module2.exports.reflinkFile = reflinkFile;
    module2.exports.reflinkFileSync = reflinkFileSync;
  }
});

// ../node_modules/.pnpm/@reflink+reflink@0.1.19/node_modules/@reflink/reflink/index.js
var require_reflink = __commonJS({
  "../node_modules/.pnpm/@reflink+reflink@0.1.19/node_modules/@reflink/reflink/index.js"(exports2, module2) {
    var binding = require_binding();
    function createReflinkError(reflinkError) {
      const error = new Error(reflinkError.message);
      return Object.assign(error, {
        path: reflinkError.path,
        dest: reflinkError.dest,
        code: reflinkError.code,
        errno: reflinkError.errno
      });
    }
    function handleReflinkResult(result) {
      if (typeof result === "number") {
        return result;
      } else {
        throw createReflinkError(result);
      }
    }
    var reflinkFile = (src, dst) => binding.reflinkFile(src, dst).then(handleReflinkResult);
    var reflinkFileSync = (src, dst) => handleReflinkResult(binding.reflinkFileSync(src, dst));
    module2.exports = {
      reflinkFile,
      reflinkFileSync
    };
  }
});

// ../fs/indexed-pkg-importer/lib/index.js
var require_lib8 = __commonJS({
  "../fs/indexed-pkg-importer/lib/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.createIndexedPkgImporter = createIndexedPkgImporter;
    exports2.copyPkg = copyPkg;
    var assert_1 = __importDefault(require("assert"));
    var fs_1 = require("fs");
    var util_1 = __importDefault(require("util"));
    var graceful_fs_1 = __importDefault(require_lib());
    var path_1 = __importDefault(require("path"));
    var logger_1 = require_lib5();
    var core_loggers_1 = require_lib6();
    var importIndexedDir_js_1 = require_importIndexedDir();
    function createIndexedPkgImporter(packageImportMethod) {
      const importPackage = createImportPackage(packageImportMethod);
      return importPackage;
    }
    function createImportPackage(packageImportMethod) {
      switch (packageImportMethod ?? "auto") {
        case "clone":
          core_loggers_1.packageImportMethodLogger.debug({ method: "clone" });
          return clonePkg.bind(null, createCloneFunction());
        case "hardlink":
          core_loggers_1.packageImportMethodLogger.debug({ method: "hardlink" });
          return hardlinkPkg.bind(null, linkOrCopy);
        case "auto": {
          return createAutoImporter();
        }
        case "clone-or-copy":
          return createCloneOrCopyImporter();
        case "copy":
          core_loggers_1.packageImportMethodLogger.debug({ method: "copy" });
          return copyPkg;
        default:
          throw new Error(`Unknown package import method ${packageImportMethod}`);
      }
    }
    function createAutoImporter() {
      let auto = initialAuto;
      return (to, opts) => auto(to, opts);
      function initialAuto(to, opts) {
        if (process.platform !== "win32") {
          try {
            const _clonePkg = clonePkg.bind(null, createCloneFunction());
            if (!_clonePkg(to, opts))
              return void 0;
            core_loggers_1.packageImportMethodLogger.debug({ method: "clone" });
            auto = _clonePkg;
            return "clone";
          } catch {
          }
        }
        try {
          if (!hardlinkPkg(graceful_fs_1.default.linkSync, to, opts))
            return void 0;
          core_loggers_1.packageImportMethodLogger.debug({ method: "hardlink" });
          auto = hardlinkPkg.bind(null, linkOrCopy);
          return "hardlink";
        } catch (err) {
          (0, assert_1.default)(util_1.default.types.isNativeError(err));
          if (err.message.startsWith("EXDEV: cross-device link not permitted")) {
            (0, logger_1.globalWarn)(err.message);
            (0, logger_1.globalInfo)("Falling back to copying packages from store");
            core_loggers_1.packageImportMethodLogger.debug({ method: "copy" });
            auto = copyPkg;
            return auto(to, opts);
          }
          core_loggers_1.packageImportMethodLogger.debug({ method: "hardlink" });
          auto = hardlinkPkg.bind(null, linkOrCopy);
          return auto(to, opts);
        }
      }
    }
    function createCloneOrCopyImporter() {
      let auto = initialAuto;
      return (to, opts) => auto(to, opts);
      function initialAuto(to, opts) {
        try {
          const _clonePkg = clonePkg.bind(null, createCloneFunction());
          if (!_clonePkg(to, opts))
            return void 0;
          core_loggers_1.packageImportMethodLogger.debug({ method: "clone" });
          auto = _clonePkg;
          return "clone";
        } catch {
        }
        core_loggers_1.packageImportMethodLogger.debug({ method: "copy" });
        auto = copyPkg;
        return auto(to, opts);
      }
    }
    function clonePkg(clone, to, opts) {
      if (opts.resolvedFrom !== "store" || opts.force || !pkgExistsAtTargetDir(to, opts.filesMap)) {
        (0, importIndexedDir_js_1.importIndexedDir)(clone, to, opts.filesMap, opts);
        return "clone";
      }
      return void 0;
    }
    function pkgExistsAtTargetDir(targetDir, filesMap) {
      return (0, fs_1.existsSync)(path_1.default.join(targetDir, pickFileFromFilesMap(filesMap)));
    }
    function pickFileFromFilesMap(filesMap) {
      if (filesMap["package.json"]) {
        return "package.json";
      }
      const files = Object.keys(filesMap);
      if (files.length === 0) {
        throw new Error("pickFileFromFilesMap cannot pick a file from an empty FilesMap");
      }
      return files[0];
    }
    function createCloneFunction() {
      if (process.platform === "darwin" || process.platform === "win32") {
        const { reflinkFileSync } = require_reflink();
        return (fr, to) => {
          try {
            reflinkFileSync(fr, to);
          } catch (err) {
            if (!util_1.default.types.isNativeError(err) || !("code" in err) || err.code !== "EEXIST")
              throw err;
          }
        };
      }
      return (src, dest) => {
        try {
          graceful_fs_1.default.copyFileSync(src, dest, fs_1.constants.COPYFILE_FICLONE_FORCE);
        } catch (err) {
          if (!(util_1.default.types.isNativeError(err) && "code" in err && err.code === "EEXIST"))
            throw err;
        }
      };
    }
    function hardlinkPkg(importFile, to, opts) {
      if (opts.force || shouldRelinkPkg(to, opts)) {
        (0, importIndexedDir_js_1.importIndexedDir)(importFile, to, opts.filesMap, opts);
        return "hardlink";
      }
      return void 0;
    }
    function shouldRelinkPkg(to, opts) {
      if (opts.disableRelinkLocalDirDeps && opts.resolvedFrom === "local-dir") {
        try {
          const files = graceful_fs_1.default.readdirSync(to);
          return files.length === 0 || files.length === 1 && files[0] === "node_modules";
        } catch {
          return true;
        }
      }
      return opts.resolvedFrom !== "store" || !pkgLinkedToStore(opts.filesMap, to);
    }
    function linkOrCopy(existingPath, newPath) {
      try {
        graceful_fs_1.default.linkSync(existingPath, newPath);
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "EEXIST")
          return;
        graceful_fs_1.default.copyFileSync(existingPath, newPath);
      }
    }
    function pkgLinkedToStore(filesMap, linkedPkgDir) {
      const filename = pickFileFromFilesMap(filesMap);
      const linkedFile = path_1.default.join(linkedPkgDir, filename);
      let stats0;
      try {
        stats0 = graceful_fs_1.default.statSync(linkedFile);
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT")
          return false;
      }
      const stats1 = graceful_fs_1.default.statSync(filesMap[filename]);
      if (stats0.ino === stats1.ino)
        return true;
      (0, logger_1.globalInfo)(`Relinking ${linkedPkgDir} from the store`);
      return false;
    }
    function copyPkg(to, opts) {
      if (opts.resolvedFrom !== "store" || opts.force || !pkgExistsAtTargetDir(to, opts.filesMap)) {
        (0, importIndexedDir_js_1.importIndexedDir)(graceful_fs_1.default.copyFileSync, to, opts.filesMap, opts);
        return "copy";
      }
      return void 0;
    }
  }
});

// ../node_modules/.pnpm/mimic-fn@3.1.0/node_modules/mimic-fn/index.js
var require_mimic_fn = __commonJS({
  "../node_modules/.pnpm/mimic-fn@3.1.0/node_modules/mimic-fn/index.js"(exports2, module2) {
    "use strict";
    var copyProperty = (to, from, property, ignoreNonConfigurable) => {
      if (property === "length" || property === "prototype") {
        return;
      }
      if (property === "arguments" || property === "caller") {
        return;
      }
      const toDescriptor = Object.getOwnPropertyDescriptor(to, property);
      const fromDescriptor = Object.getOwnPropertyDescriptor(from, property);
      if (!canCopyProperty(toDescriptor, fromDescriptor) && ignoreNonConfigurable) {
        return;
      }
      Object.defineProperty(to, property, fromDescriptor);
    };
    var canCopyProperty = function(toDescriptor, fromDescriptor) {
      return toDescriptor === void 0 || toDescriptor.configurable || toDescriptor.writable === fromDescriptor.writable && toDescriptor.enumerable === fromDescriptor.enumerable && toDescriptor.configurable === fromDescriptor.configurable && (toDescriptor.writable || toDescriptor.value === fromDescriptor.value);
    };
    var changePrototype = (to, from) => {
      const fromPrototype = Object.getPrototypeOf(from);
      if (fromPrototype === Object.getPrototypeOf(to)) {
        return;
      }
      Object.setPrototypeOf(to, fromPrototype);
    };
    var wrappedToString = (withName, fromBody) => `/* Wrapped ${withName}*/
${fromBody}`;
    var toStringDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, "toString");
    var toStringName = Object.getOwnPropertyDescriptor(Function.prototype.toString, "name");
    var changeToString = (to, from, name) => {
      const withName = name === "" ? "" : `with ${name.trim()}() `;
      const newToString = wrappedToString.bind(null, withName, from.toString());
      Object.defineProperty(newToString, "name", toStringName);
      Object.defineProperty(to, "toString", { ...toStringDescriptor, value: newToString });
    };
    var mimicFn = (to, from, { ignoreNonConfigurable = false } = {}) => {
      const { name } = to;
      for (const property of Reflect.ownKeys(from)) {
        copyProperty(to, from, property, ignoreNonConfigurable);
      }
      changePrototype(to, from);
      changeToString(to, from, name);
      return to;
    };
    module2.exports = mimicFn;
  }
});

// ../node_modules/.pnpm/p-defer@1.0.0/node_modules/p-defer/index.js
var require_p_defer = __commonJS({
  "../node_modules/.pnpm/p-defer@1.0.0/node_modules/p-defer/index.js"(exports2, module2) {
    "use strict";
    module2.exports = () => {
      const ret = {};
      ret.promise = new Promise((resolve, reject) => {
        ret.resolve = resolve;
        ret.reject = reject;
      });
      return ret;
    };
  }
});

// ../node_modules/.pnpm/map-age-cleaner@0.1.3/node_modules/map-age-cleaner/dist/index.js
var require_dist = __commonJS({
  "../node_modules/.pnpm/map-age-cleaner@0.1.3/node_modules/map-age-cleaner/dist/index.js"(exports2, module2) {
    "use strict";
    var __awaiter = exports2 && exports2.__awaiter || function(thisArg, _arguments, P, generator) {
      return new (P || (P = Promise))(function(resolve, reject) {
        function fulfilled(value) {
          try {
            step(generator.next(value));
          } catch (e) {
            reject(e);
          }
        }
        function rejected(value) {
          try {
            step(generator["throw"](value));
          } catch (e) {
            reject(e);
          }
        }
        function step(result) {
          result.done ? resolve(result.value) : new P(function(resolve2) {
            resolve2(result.value);
          }).then(fulfilled, rejected);
        }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
      });
    };
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    var p_defer_1 = __importDefault(require_p_defer());
    function mapAgeCleaner(map, property = "maxAge") {
      let processingKey;
      let processingTimer;
      let processingDeferred;
      const cleanup = () => __awaiter(this, void 0, void 0, function* () {
        if (processingKey !== void 0) {
          return;
        }
        const setupTimer = (item) => __awaiter(this, void 0, void 0, function* () {
          processingDeferred = p_defer_1.default();
          const delay = item[1][property] - Date.now();
          if (delay <= 0) {
            map.delete(item[0]);
            processingDeferred.resolve();
            return;
          }
          processingKey = item[0];
          processingTimer = setTimeout(() => {
            map.delete(item[0]);
            if (processingDeferred) {
              processingDeferred.resolve();
            }
          }, delay);
          if (typeof processingTimer.unref === "function") {
            processingTimer.unref();
          }
          return processingDeferred.promise;
        });
        try {
          for (const entry of map) {
            yield setupTimer(entry);
          }
        } catch (_a) {
        }
        processingKey = void 0;
      });
      const reset = () => {
        processingKey = void 0;
        if (processingTimer !== void 0) {
          clearTimeout(processingTimer);
          processingTimer = void 0;
        }
        if (processingDeferred !== void 0) {
          processingDeferred.reject(void 0);
          processingDeferred = void 0;
        }
      };
      const originalSet = map.set.bind(map);
      map.set = (key, value) => {
        if (map.has(key)) {
          map.delete(key);
        }
        const result = originalSet(key, value);
        if (processingKey && processingKey === key) {
          reset();
        }
        cleanup();
        return result;
      };
      cleanup();
      return map;
    }
    exports2.default = mapAgeCleaner;
    module2.exports = mapAgeCleaner;
    module2.exports.default = mapAgeCleaner;
  }
});

// ../node_modules/.pnpm/mem@8.1.1/node_modules/mem/dist/index.js
var require_dist2 = __commonJS({
  "../node_modules/.pnpm/mem@8.1.1/node_modules/mem/dist/index.js"(exports2, module2) {
    "use strict";
    var mimicFn = require_mimic_fn();
    var mapAgeCleaner = require_dist();
    var decoratorInstanceMap = /* @__PURE__ */ new WeakMap();
    var cacheStore = /* @__PURE__ */ new WeakMap();
    var mem = (fn, { cacheKey, cache = /* @__PURE__ */ new Map(), maxAge } = {}) => {
      if (typeof maxAge === "number") {
        mapAgeCleaner(cache);
      }
      const memoized = function(...arguments_) {
        const key = cacheKey ? cacheKey(arguments_) : arguments_[0];
        const cacheItem = cache.get(key);
        if (cacheItem) {
          return cacheItem.data;
        }
        const result = fn.apply(this, arguments_);
        cache.set(key, {
          data: result,
          maxAge: maxAge ? Date.now() + maxAge : Number.POSITIVE_INFINITY
        });
        return result;
      };
      mimicFn(memoized, fn, {
        ignoreNonConfigurable: true
      });
      cacheStore.set(memoized, cache);
      return memoized;
    };
    mem.decorator = (options = {}) => (target, propertyKey, descriptor) => {
      const input = target[propertyKey];
      if (typeof input !== "function") {
        throw new TypeError("The decorated value must be a function");
      }
      delete descriptor.value;
      delete descriptor.writable;
      descriptor.get = function() {
        if (!decoratorInstanceMap.has(this)) {
          const value = mem(input, options);
          decoratorInstanceMap.set(this, value);
          return value;
        }
        return decoratorInstanceMap.get(this);
      };
    };
    mem.clear = (fn) => {
      const cache = cacheStore.get(fn);
      if (!cache) {
        throw new TypeError("Can't clear a function that was not memoized!");
      }
      if (typeof cache.clear !== "function") {
        throw new TypeError("The cache Map can't be cleared!");
      }
      cache.clear();
    };
    module2.exports = mem;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isPlaceholder.js
var require_isPlaceholder = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isPlaceholder.js"(exports2, module2) {
    function _isPlaceholder(a) {
      return a != null && typeof a === "object" && a["@@functional/placeholder"] === true;
    }
    module2.exports = _isPlaceholder;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_curry1.js
var require_curry1 = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_curry1.js"(exports2, module2) {
    var _isPlaceholder = require_isPlaceholder();
    function _curry1(fn) {
      return function f1(a) {
        if (arguments.length === 0 || _isPlaceholder(a)) {
          return f1;
        } else {
          return fn.apply(this, arguments);
        }
      };
    }
    module2.exports = _curry1;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_curry2.js
var require_curry2 = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_curry2.js"(exports2, module2) {
    var _curry1 = require_curry1();
    var _isPlaceholder = require_isPlaceholder();
    function _curry2(fn) {
      return function f2(a, b) {
        switch (arguments.length) {
          case 0:
            return f2;
          case 1:
            return _isPlaceholder(a) ? f2 : _curry1(function(_b) {
              return fn(a, _b);
            });
          default:
            return _isPlaceholder(a) && _isPlaceholder(b) ? f2 : _isPlaceholder(a) ? _curry1(function(_a) {
              return fn(_a, b);
            }) : _isPlaceholder(b) ? _curry1(function(_b) {
              return fn(a, _b);
            }) : fn(a, b);
        }
      };
    }
    module2.exports = _curry2;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isArray.js
var require_isArray = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isArray.js"(exports2, module2) {
    module2.exports = Array.isArray || function _isArray(val) {
      return val != null && val.length >= 0 && Object.prototype.toString.call(val) === "[object Array]";
    };
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isTransformer.js
var require_isTransformer = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isTransformer.js"(exports2, module2) {
    function _isTransformer(obj) {
      return obj != null && typeof obj["@@transducer/step"] === "function";
    }
    module2.exports = _isTransformer;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_dispatchable.js
var require_dispatchable = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_dispatchable.js"(exports2, module2) {
    var _isArray = require_isArray();
    var _isTransformer = require_isTransformer();
    function _dispatchable(methodNames, transducerCreator, fn) {
      return function() {
        if (arguments.length === 0) {
          return fn();
        }
        var obj = arguments[arguments.length - 1];
        if (!_isArray(obj)) {
          var idx = 0;
          while (idx < methodNames.length) {
            if (typeof obj[methodNames[idx]] === "function") {
              return obj[methodNames[idx]].apply(obj, Array.prototype.slice.call(arguments, 0, -1));
            }
            idx += 1;
          }
          if (_isTransformer(obj)) {
            var transducer = transducerCreator.apply(null, Array.prototype.slice.call(arguments, 0, -1));
            return transducer(obj);
          }
        }
        return fn.apply(this, arguments);
      };
    }
    module2.exports = _dispatchable;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_map.js
var require_map = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_map.js"(exports2, module2) {
    function _map(fn, functor) {
      var idx = 0;
      var len = functor.length;
      var result = Array(len);
      while (idx < len) {
        result[idx] = fn(functor[idx]);
        idx += 1;
      }
      return result;
    }
    module2.exports = _map;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isString.js
var require_isString = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isString.js"(exports2, module2) {
    function _isString(x) {
      return Object.prototype.toString.call(x) === "[object String]";
    }
    module2.exports = _isString;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isArrayLike.js
var require_isArrayLike = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isArrayLike.js"(exports2, module2) {
    var _curry1 = require_curry1();
    var _isArray = require_isArray();
    var _isString = require_isString();
    var _isArrayLike = /* @__PURE__ */ _curry1(function isArrayLike(x) {
      if (_isArray(x)) {
        return true;
      }
      if (!x) {
        return false;
      }
      if (typeof x !== "object") {
        return false;
      }
      if (_isString(x)) {
        return false;
      }
      if (x.length === 0) {
        return true;
      }
      if (x.length > 0) {
        return x.hasOwnProperty(0) && x.hasOwnProperty(x.length - 1);
      }
      return false;
    });
    module2.exports = _isArrayLike;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_xwrap.js
var require_xwrap = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_xwrap.js"(exports2, module2) {
    var XWrap = /* @__PURE__ */ (function() {
      function XWrap2(fn) {
        this.f = fn;
      }
      XWrap2.prototype["@@transducer/init"] = function() {
        throw new Error("init not implemented on XWrap");
      };
      XWrap2.prototype["@@transducer/result"] = function(acc) {
        return acc;
      };
      XWrap2.prototype["@@transducer/step"] = function(acc, x) {
        return this.f(acc, x);
      };
      return XWrap2;
    })();
    function _xwrap(fn) {
      return new XWrap(fn);
    }
    module2.exports = _xwrap;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_arity.js
var require_arity = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_arity.js"(exports2, module2) {
    function _arity(n, fn) {
      switch (n) {
        case 0:
          return function() {
            return fn.apply(this, arguments);
          };
        case 1:
          return function(a0) {
            return fn.apply(this, arguments);
          };
        case 2:
          return function(a0, a1) {
            return fn.apply(this, arguments);
          };
        case 3:
          return function(a0, a1, a2) {
            return fn.apply(this, arguments);
          };
        case 4:
          return function(a0, a1, a2, a3) {
            return fn.apply(this, arguments);
          };
        case 5:
          return function(a0, a1, a2, a3, a4) {
            return fn.apply(this, arguments);
          };
        case 6:
          return function(a0, a1, a2, a3, a4, a5) {
            return fn.apply(this, arguments);
          };
        case 7:
          return function(a0, a1, a2, a3, a4, a5, a6) {
            return fn.apply(this, arguments);
          };
        case 8:
          return function(a0, a1, a2, a3, a4, a5, a6, a7) {
            return fn.apply(this, arguments);
          };
        case 9:
          return function(a0, a1, a2, a3, a4, a5, a6, a7, a8) {
            return fn.apply(this, arguments);
          };
        case 10:
          return function(a0, a1, a2, a3, a4, a5, a6, a7, a8, a9) {
            return fn.apply(this, arguments);
          };
        default:
          throw new Error("First argument to _arity must be a non-negative integer no greater than ten");
      }
    }
    module2.exports = _arity;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/bind.js
var require_bind = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/bind.js"(exports2, module2) {
    var _arity = require_arity();
    var _curry2 = require_curry2();
    var bind = /* @__PURE__ */ _curry2(function bind2(fn, thisObj) {
      return _arity(fn.length, function() {
        return fn.apply(thisObj, arguments);
      });
    });
    module2.exports = bind;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_reduce.js
var require_reduce = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_reduce.js"(exports2, module2) {
    var _isArrayLike = require_isArrayLike();
    var _xwrap = require_xwrap();
    var bind = require_bind();
    function _arrayReduce(xf, acc, list) {
      var idx = 0;
      var len = list.length;
      while (idx < len) {
        acc = xf["@@transducer/step"](acc, list[idx]);
        if (acc && acc["@@transducer/reduced"]) {
          acc = acc["@@transducer/value"];
          break;
        }
        idx += 1;
      }
      return xf["@@transducer/result"](acc);
    }
    function _iterableReduce(xf, acc, iter) {
      var step = iter.next();
      while (!step.done) {
        acc = xf["@@transducer/step"](acc, step.value);
        if (acc && acc["@@transducer/reduced"]) {
          acc = acc["@@transducer/value"];
          break;
        }
        step = iter.next();
      }
      return xf["@@transducer/result"](acc);
    }
    function _methodReduce(xf, acc, obj, methodName) {
      return xf["@@transducer/result"](obj[methodName](bind(xf["@@transducer/step"], xf), acc));
    }
    var symIterator = typeof Symbol !== "undefined" ? Symbol.iterator : "@@iterator";
    function _reduce(fn, acc, list) {
      if (typeof fn === "function") {
        fn = _xwrap(fn);
      }
      if (_isArrayLike(list)) {
        return _arrayReduce(fn, acc, list);
      }
      if (typeof list["fantasy-land/reduce"] === "function") {
        return _methodReduce(fn, acc, list, "fantasy-land/reduce");
      }
      if (list[symIterator] != null) {
        return _iterableReduce(fn, acc, list[symIterator]());
      }
      if (typeof list.next === "function") {
        return _iterableReduce(fn, acc, list);
      }
      if (typeof list.reduce === "function") {
        return _methodReduce(fn, acc, list, "reduce");
      }
      throw new TypeError("reduce: list must be array or iterable");
    }
    module2.exports = _reduce;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_xfBase.js
var require_xfBase = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_xfBase.js"(exports2, module2) {
    module2.exports = {
      init: function() {
        return this.xf["@@transducer/init"]();
      },
      result: function(result) {
        return this.xf["@@transducer/result"](result);
      }
    };
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_xmap.js
var require_xmap = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_xmap.js"(exports2, module2) {
    var _curry2 = require_curry2();
    var _xfBase = require_xfBase();
    var XMap = /* @__PURE__ */ (function() {
      function XMap2(f, xf) {
        this.xf = xf;
        this.f = f;
      }
      XMap2.prototype["@@transducer/init"] = _xfBase.init;
      XMap2.prototype["@@transducer/result"] = _xfBase.result;
      XMap2.prototype["@@transducer/step"] = function(result, input) {
        return this.xf["@@transducer/step"](result, this.f(input));
      };
      return XMap2;
    })();
    var _xmap = /* @__PURE__ */ _curry2(function _xmap2(f, xf) {
      return new XMap(f, xf);
    });
    module2.exports = _xmap;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_curryN.js
var require_curryN = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_curryN.js"(exports2, module2) {
    var _arity = require_arity();
    var _isPlaceholder = require_isPlaceholder();
    function _curryN(length, received, fn) {
      return function() {
        var combined = [];
        var argsIdx = 0;
        var left = length;
        var combinedIdx = 0;
        while (combinedIdx < received.length || argsIdx < arguments.length) {
          var result;
          if (combinedIdx < received.length && (!_isPlaceholder(received[combinedIdx]) || argsIdx >= arguments.length)) {
            result = received[combinedIdx];
          } else {
            result = arguments[argsIdx];
            argsIdx += 1;
          }
          combined[combinedIdx] = result;
          if (!_isPlaceholder(result)) {
            left -= 1;
          }
          combinedIdx += 1;
        }
        return left <= 0 ? fn.apply(this, combined) : _arity(left, _curryN(length, combined, fn));
      };
    }
    module2.exports = _curryN;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/curryN.js
var require_curryN2 = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/curryN.js"(exports2, module2) {
    var _arity = require_arity();
    var _curry1 = require_curry1();
    var _curry2 = require_curry2();
    var _curryN = require_curryN();
    var curryN = /* @__PURE__ */ _curry2(function curryN2(length, fn) {
      if (length === 1) {
        return _curry1(fn);
      }
      return _arity(length, _curryN(length, [], fn));
    });
    module2.exports = curryN;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_has.js
var require_has = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_has.js"(exports2, module2) {
    function _has(prop, obj) {
      return Object.prototype.hasOwnProperty.call(obj, prop);
    }
    module2.exports = _has;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isArguments.js
var require_isArguments = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/internal/_isArguments.js"(exports2, module2) {
    var _has = require_has();
    var toString = Object.prototype.toString;
    var _isArguments = /* @__PURE__ */ (function() {
      return toString.call(arguments) === "[object Arguments]" ? function _isArguments2(x) {
        return toString.call(x) === "[object Arguments]";
      } : function _isArguments2(x) {
        return _has("callee", x);
      };
    })();
    module2.exports = _isArguments;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/keys.js
var require_keys = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/keys.js"(exports2, module2) {
    var _curry1 = require_curry1();
    var _has = require_has();
    var _isArguments = require_isArguments();
    var hasEnumBug = !/* @__PURE__ */ {
      toString: null
    }.propertyIsEnumerable("toString");
    var nonEnumerableProps = ["constructor", "valueOf", "isPrototypeOf", "toString", "propertyIsEnumerable", "hasOwnProperty", "toLocaleString"];
    var hasArgsEnumBug = /* @__PURE__ */ (function() {
      "use strict";
      return arguments.propertyIsEnumerable("length");
    })();
    var contains = function contains2(list, item) {
      var idx = 0;
      while (idx < list.length) {
        if (list[idx] === item) {
          return true;
        }
        idx += 1;
      }
      return false;
    };
    var keys = typeof Object.keys === "function" && !hasArgsEnumBug ? /* @__PURE__ */ _curry1(function keys2(obj) {
      return Object(obj) !== obj ? [] : Object.keys(obj);
    }) : /* @__PURE__ */ _curry1(function keys2(obj) {
      if (Object(obj) !== obj) {
        return [];
      }
      var prop, nIdx;
      var ks = [];
      var checkArgsLength = hasArgsEnumBug && _isArguments(obj);
      for (prop in obj) {
        if (_has(prop, obj) && (!checkArgsLength || prop !== "length")) {
          ks[ks.length] = prop;
        }
      }
      if (hasEnumBug) {
        nIdx = nonEnumerableProps.length - 1;
        while (nIdx >= 0) {
          prop = nonEnumerableProps[nIdx];
          if (_has(prop, obj) && !contains(ks, prop)) {
            ks[ks.length] = prop;
          }
          nIdx -= 1;
        }
      }
      return ks;
    });
    module2.exports = keys;
  }
});

// ../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/map.js
var require_map2 = __commonJS({
  "../node_modules/.pnpm/@pnpm+ramda@0.28.1/node_modules/@pnpm/ramda/src/map.js"(exports2, module2) {
    var _curry2 = require_curry2();
    var _dispatchable = require_dispatchable();
    var _map = require_map();
    var _reduce = require_reduce();
    var _xmap = require_xmap();
    var curryN = require_curryN2();
    var keys = require_keys();
    var map = /* @__PURE__ */ _curry2(
      /* @__PURE__ */ _dispatchable(["fantasy-land/map", "map"], _xmap, function map2(fn, functor) {
        switch (Object.prototype.toString.call(functor)) {
          case "[object Function]":
            return curryN(functor.length, function() {
              return fn.call(this, functor.apply(this, arguments));
            });
          case "[object Object]":
            return _reduce(function(acc, key) {
              acc[key] = fn(functor[key]);
              return acc;
            }, {}, keys(functor));
          default:
            return _map(fn, functor);
        }
      })
    );
    module2.exports = map;
  }
});

// ../store/create-cafs-store/lib/index.js
var require_lib9 = __commonJS({
  "../store/create-cafs-store/lib/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.createPackageImporterAsync = createPackageImporterAsync;
    exports2.createCafsStore = createCafsStore;
    var fs_1 = require("fs");
    var path_1 = __importDefault(require("path"));
    var store_cafs_1 = require_lib4();
    var fs_indexed_pkg_importer_1 = require_lib8();
    var mem_1 = __importDefault(require_dist2());
    var path_temp_1 = __importDefault(require_path_temp());
    var map_1 = __importDefault(require_map2());
    function createPackageImporterAsync(opts) {
      const cachedImporterCreator = opts.importIndexedPackage ? () => opts.importIndexedPackage : (0, mem_1.default)(fs_indexed_pkg_importer_1.createIndexedPkgImporter);
      const packageImportMethod = opts.packageImportMethod;
      const gfm = getFlatMap.bind(null, opts.storeDir);
      return async (to, opts2) => {
        const { filesMap, isBuilt } = gfm(opts2.filesResponse, opts2.sideEffectsCacheKey);
        const willBeBuilt = !isBuilt && opts2.requiresBuild;
        const pkgImportMethod = willBeBuilt ? "clone-or-copy" : opts2.filesResponse.packageImportMethod ?? packageImportMethod;
        const impPkg = cachedImporterCreator(pkgImportMethod);
        const importMethod = await impPkg(to, {
          disableRelinkLocalDirDeps: opts2.disableRelinkLocalDirDeps,
          filesMap,
          resolvedFrom: opts2.filesResponse.resolvedFrom,
          force: opts2.force,
          keepModulesDir: Boolean(opts2.keepModulesDir)
        });
        return { importMethod, isBuilt };
      };
    }
    function createPackageImporter(opts) {
      const cachedImporterCreator = opts.importIndexedPackage ? () => opts.importIndexedPackage : (0, mem_1.default)(fs_indexed_pkg_importer_1.createIndexedPkgImporter);
      const packageImportMethod = opts.packageImportMethod;
      const gfm = getFlatMap.bind(null, opts.storeDir);
      return (to, opts2) => {
        const { filesMap, isBuilt } = gfm(opts2.filesResponse, opts2.sideEffectsCacheKey);
        const willBeBuilt = !isBuilt && opts2.requiresBuild;
        const pkgImportMethod = willBeBuilt ? "clone-or-copy" : opts2.filesResponse.packageImportMethod ?? packageImportMethod;
        const impPkg = cachedImporterCreator(pkgImportMethod);
        const importMethod = impPkg(to, {
          disableRelinkLocalDirDeps: opts2.disableRelinkLocalDirDeps,
          filesMap,
          resolvedFrom: opts2.filesResponse.resolvedFrom,
          force: opts2.force,
          keepModulesDir: Boolean(opts2.keepModulesDir)
        });
        return { importMethod, isBuilt };
      };
    }
    function getFlatMap(storeDir, filesResponse, targetEngine) {
      let isBuilt;
      let filesIndex;
      if (targetEngine && filesResponse.sideEffects?.[targetEngine] != null) {
        filesIndex = applySideEffectsDiff(filesResponse.filesIndex, filesResponse.sideEffects?.[targetEngine]);
        isBuilt = true;
      } else if (!filesResponse.unprocessed) {
        return {
          filesMap: filesResponse.filesIndex,
          isBuilt: false
        };
      } else {
        filesIndex = filesResponse.filesIndex;
        isBuilt = false;
      }
      const filesMap = (0, map_1.default)(({ integrity, mode }) => (0, store_cafs_1.getFilePathByModeInCafs)(storeDir, integrity, mode), filesIndex);
      return { filesMap, isBuilt };
    }
    function applySideEffectsDiff(baseFiles, { added, deleted }) {
      const filesWithSideEffects = { ...added };
      for (const fileName in baseFiles) {
        if (!deleted?.includes(fileName) && !filesWithSideEffects[fileName]) {
          filesWithSideEffects[fileName] = baseFiles[fileName];
        }
      }
      return filesWithSideEffects;
    }
    function createCafsStore(storeDir, opts) {
      const baseTempDir = path_1.default.join(storeDir, "tmp");
      const importPackage = createPackageImporter({
        importIndexedPackage: opts?.importPackage,
        packageImportMethod: opts?.packageImportMethod,
        storeDir
      });
      return {
        ...(0, store_cafs_1.createCafs)(storeDir, opts),
        storeDir,
        importPackage,
        tempDir: async () => {
          const tmpDir = (0, path_temp_1.default)(baseTempDir);
          await fs_1.promises.mkdir(tmpDir, { recursive: true });
          return tmpDir;
        }
      };
    }
  }
});

// ../crypto/polyfill/lib/index.js
var require_lib10 = __commonJS({
  "../crypto/polyfill/lib/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.hash = void 0;
    var crypto_1 = __importDefault(require("crypto"));
    exports2.hash = // @ts-expect-error -- crypto.hash is supported in Node 21.7.0+, 20.12.0+
    crypto_1.default.hash ?? ((algorithm, data, outputEncoding) => crypto_1.default.createHash(algorithm).update(data).digest(outputEncoding));
  }
});

// ../exec/pkg-requires-build/lib/index.js
var require_lib11 = __commonJS({
  "../exec/pkg-requires-build/lib/index.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.pkgRequiresBuild = pkgRequiresBuild;
    function pkgRequiresBuild(manifest, filesIndex) {
      return Boolean(manifest?.scripts != null && (Boolean(manifest.scripts.preinstall) || Boolean(manifest.scripts.install) || Boolean(manifest.scripts.postinstall)) || filesIncludeInstallScripts(filesIndex));
    }
    function filesIncludeInstallScripts(filesIndex) {
      return filesIndex["binding.gyp"] != null || Object.keys(filesIndex).some((filename) => !(filename.match(/^\.hooks[\\/]/) == null));
    }
  }
});

// ../fs/hard-link-dir/lib/index.js
var require_lib12 = __commonJS({
  "../fs/hard-link-dir/lib/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.hardLinkDir = hardLinkDir;
    var assert_1 = __importDefault(require("assert"));
    var path_1 = __importDefault(require("path"));
    var util_1 = __importDefault(require("util"));
    var fs_1 = __importDefault(require("fs"));
    var logger_1 = require_lib5();
    var graceful_fs_1 = __importDefault(require_lib());
    var rename_overwrite_1 = require_rename_overwrite();
    var path_temp_1 = __importDefault(require_path_temp());
    function hardLinkDir(src, destDirs) {
      if (destDirs.length === 0)
        return;
      const filteredDestDirs = [];
      const tempDestDirs = [];
      for (const destDir of destDirs) {
        if (path_1.default.relative(destDir, src) === "") {
          continue;
        }
        filteredDestDirs.push(destDir);
        tempDestDirs.push((0, path_temp_1.default)(path_1.default.dirname(destDir)));
      }
      _hardLinkDir(src, tempDestDirs, true);
      for (let i = 0; i < filteredDestDirs.length; i++) {
        (0, rename_overwrite_1.sync)(tempDestDirs[i], filteredDestDirs[i]);
      }
    }
    function _hardLinkDir(src, destDirs, isRoot) {
      let files = [];
      try {
        files = fs_1.default.readdirSync(src);
      } catch (err) {
        if (!isRoot || !(util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT"))
          throw err;
        (0, logger_1.globalWarn)(`Source directory not found when creating hardLinks for: ${src}. Creating destinations as empty: ${destDirs.join(", ")}`);
        for (const dir of destDirs) {
          graceful_fs_1.default.mkdirSync(dir, { recursive: true });
        }
        return;
      }
      for (const file of files) {
        if (file === "node_modules")
          continue;
        const srcFile = path_1.default.join(src, file);
        if (fs_1.default.lstatSync(srcFile).isDirectory()) {
          const destSubdirs = destDirs.map((destDir) => {
            const destSubdir = path_1.default.join(destDir, file);
            try {
              graceful_fs_1.default.mkdirSync(destSubdir, { recursive: true });
            } catch (err) {
              if (!(util_1.default.types.isNativeError(err) && "code" in err && err.code === "EEXIST"))
                throw err;
            }
            return destSubdir;
          });
          _hardLinkDir(srcFile, destSubdirs);
          continue;
        }
        for (const destDir of destDirs) {
          const destFile = path_1.default.join(destDir, file);
          try {
            linkOrCopyFile(srcFile, destFile);
          } catch (err) {
            if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") {
              continue;
            }
            throw err;
          }
        }
      }
    }
    function linkOrCopyFile(srcFile, destFile) {
      try {
        linkOrCopy(srcFile, destFile);
      } catch (err) {
        (0, assert_1.default)(util_1.default.types.isNativeError(err));
        if ("code" in err && err.code === "ENOENT") {
          graceful_fs_1.default.mkdirSync(path_1.default.dirname(destFile), { recursive: true });
          linkOrCopy(srcFile, destFile);
          return;
        }
        if (!("code" in err && err.code === "EEXIST")) {
          throw err;
        }
      }
    }
    function linkOrCopy(srcFile, destFile) {
      try {
        graceful_fs_1.default.linkSync(srcFile, destFile);
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && (err.code === "EXDEV" || err.code === "ENOENT")) {
          graceful_fs_1.default.copyFileSync(srcFile, destFile);
        } else {
          throw err;
        }
      }
    }
  }
});

// ../node_modules/.pnpm/rename-overwrite@6.0.3/node_modules/rename-overwrite/index.js
var require_rename_overwrite2 = __commonJS({
  "../node_modules/.pnpm/rename-overwrite@6.0.3/node_modules/rename-overwrite/index.js"(exports2, module2) {
    "use strict";
    var fs = require("fs");
    var { copySync, copy } = require_lib3();
    var path = require("path");
    var rimraf = require_rimraf();
    module2.exports = async function renameOverwrite(oldPath, newPath, retry = 0) {
      try {
        await fs.promises.rename(oldPath, newPath);
      } catch (err) {
        retry++;
        if (retry > 3) throw err;
        switch (err.code) {
          case "ENOTEMPTY":
          case "EEXIST":
          case "ENOTDIR":
            await rimraf(newPath);
            await renameOverwrite(oldPath, newPath, retry);
            break;
          // Windows Antivirus issues
          case "EPERM":
          case "EACCESS":
          case "EBUSY": {
            await rimraf(newPath);
            const start = Date.now();
            let backoff = 0;
            let lastError = err;
            while (Date.now() - start < 6e4 && (lastError.code === "EPERM" || lastError.code === "EACCESS" || lastError.code === "EBUSY")) {
              await new Promise((resolve) => setTimeout(resolve, backoff));
              try {
                await fs.promises.rename(oldPath, newPath);
                return;
              } catch (err2) {
                lastError = err2;
              }
              if (backoff < 100) {
                backoff += 10;
              }
            }
            throw lastError;
          }
          case "ENOENT":
            try {
              await fs.promises.stat(oldPath);
            } catch (statErr) {
              if (statErr.code === "ENOENT") {
                throw statErr;
              }
            }
            await fs.promises.mkdir(path.dirname(newPath), { recursive: true });
            await renameOverwrite(oldPath, newPath, retry);
            break;
          // Crossing filesystem boundaries so rename is not available
          case "EXDEV":
            try {
              await rimraf(newPath);
            } catch (rimrafErr) {
              if (rimrafErr.code !== "ENOENT") {
                throw rimrafErr;
              }
            }
            await copy(oldPath, newPath);
            await rimraf(oldPath);
            break;
          default:
            throw err;
        }
      }
    };
    module2.exports.sync = function renameOverwriteSync(oldPath, newPath, retry = 0) {
      try {
        fs.renameSync(oldPath, newPath);
      } catch (err) {
        retry++;
        if (retry > 3) throw err;
        switch (err.code) {
          // Windows Antivirus issues
          case "EPERM":
          case "EACCESS":
          case "EBUSY": {
            rimraf.sync(newPath);
            const start = Date.now();
            let backoff = 0;
            let lastError = err;
            while (Date.now() - start < 6e4 && (lastError.code === "EPERM" || lastError.code === "EACCESS" || lastError.code === "EBUSY")) {
              const waitUntil = Date.now() + backoff;
              while (waitUntil > Date.now()) {
              }
              try {
                fs.renameSync(oldPath, newPath);
                return;
              } catch (err2) {
                lastError = err2;
              }
              if (backoff < 100) {
                backoff += 10;
              }
            }
            throw lastError;
          }
          case "ENOTEMPTY":
          case "EEXIST":
          case "ENOTDIR":
            rimraf.sync(newPath);
            fs.renameSync(oldPath, newPath);
            return;
          case "ENOENT":
            fs.mkdirSync(path.dirname(newPath), { recursive: true });
            renameOverwriteSync(oldPath, newPath, retry);
            return;
          // Crossing filesystem boundaries so rename is not available
          case "EXDEV":
            try {
              rimraf.sync(newPath);
            } catch (rimrafErr) {
              if (rimrafErr.code !== "ENOENT") {
                throw rimrafErr;
              }
            }
            copySync(oldPath, newPath);
            rimraf.sync(oldPath);
            break;
          default:
            throw err;
        }
      }
    };
  }
});

// ../node_modules/.pnpm/symlink-dir@6.0.5/node_modules/symlink-dir/dist/index.js
var require_dist3 = __commonJS({
  "../node_modules/.pnpm/symlink-dir@6.0.5/node_modules/symlink-dir/dist/index.js"(exports2, module2) {
    "use strict";
    var betterPathResolve = require_better_path_resolve();
    var fs_1 = require("fs");
    var util = require("util");
    var pathLib = require("path");
    var renameOverwrite = require_rename_overwrite2();
    var IS_WINDOWS = process.platform === "win32" || /^(msys|cygwin)$/.test(process.env.OSTYPE);
    var symlinkType = IS_WINDOWS ? "junction" : "dir";
    var resolveSrc = IS_WINDOWS ? resolveSrcOnWin : resolveSrcOnNonWin;
    function resolveSrcOnWin(src, dest) {
      return `${src}\\`;
    }
    function resolveSrcOnNonWin(src, dest) {
      return pathLib.relative(pathLib.dirname(dest), src);
    }
    function symlinkDir(target, path, opts) {
      path = betterPathResolve(path);
      target = betterPathResolve(target);
      if (target === path)
        throw new Error(`Symlink path is the same as the target path (${target})`);
      target = resolveSrc(target, path);
      return forceSymlink(target, path, opts);
    }
    async function forceSymlink(target, path, opts) {
      let initialErr;
      try {
        await fs_1.promises.symlink(target, path, symlinkType);
        return { reused: false };
      } catch (err) {
        switch (err.code) {
          case "ENOENT":
            try {
              await fs_1.promises.mkdir(pathLib.dirname(path), { recursive: true });
            } catch (mkdirError) {
              mkdirError.message = `Error while trying to symlink "${target}" to "${path}". The error happened while trying to create the parent directory for the symlink target. Details: ${mkdirError}`;
              throw mkdirError;
            }
            await forceSymlink(target, path, opts);
            return { reused: false };
          case "EEXIST":
          case "EISDIR":
            initialErr = err;
            break;
          default:
            throw err;
        }
      }
      let linkString;
      try {
        linkString = await fs_1.promises.readlink(path);
      } catch (err) {
        if ((opts === null || opts === void 0 ? void 0 : opts.overwrite) === false) {
          throw initialErr;
        }
        const parentDir = pathLib.dirname(path);
        let warn;
        if (opts === null || opts === void 0 ? void 0 : opts.renameTried) {
          await fs_1.promises.unlink(path);
          warn = `Symlink wanted name was occupied by directory or file. Old entity removed: "${parentDir}${pathLib.sep}{${pathLib.basename(path)}".`;
        } else {
          const ignore = `.ignored_${pathLib.basename(path)}`;
          try {
            await renameOverwrite(path, pathLib.join(parentDir, ignore));
          } catch (error) {
            if (util.types.isNativeError(error) && "code" in error && error.code === "ENOENT") {
              throw initialErr;
            }
            throw error;
          }
          warn = `Symlink wanted name was occupied by directory or file. Old entity moved: "${parentDir}${pathLib.sep}{${pathLib.basename(path)} => ${ignore}".`;
        }
        return {
          ...await forceSymlink(target, path, { ...opts, renameTried: true }),
          warn
        };
      }
      if (pathLib.relative(target, linkString) === "") {
        return { reused: true };
      }
      if ((opts === null || opts === void 0 ? void 0 : opts.overwrite) === false) {
        throw initialErr;
      }
      try {
        await fs_1.promises.unlink(path);
      } catch (error) {
        if (!util.types.isNativeError(error) || !("code" in error) || error.code !== "ENOENT") {
          throw error;
        }
      }
      return await forceSymlink(target, path, opts);
    }
    symlinkDir["default"] = symlinkDir;
    (function(symlinkDir2) {
      function sync(target, path, opts) {
        path = betterPathResolve(path);
        target = betterPathResolve(target);
        if (target === path)
          throw new Error(`Symlink path is the same as the target path (${target})`);
        target = resolveSrc(target, path);
        return forceSymlinkSync(target, path, opts);
      }
      symlinkDir2.sync = sync;
    })(symlinkDir || (symlinkDir = {}));
    function forceSymlinkSync(target, path, opts) {
      let initialErr;
      try {
        (0, fs_1.symlinkSync)(target, path, symlinkType);
        return { reused: false };
      } catch (err) {
        initialErr = err;
        switch (err.code) {
          case "ENOENT":
            try {
              (0, fs_1.mkdirSync)(pathLib.dirname(path), { recursive: true });
            } catch (mkdirError) {
              mkdirError.message = `Error while trying to symlink "${target}" to "${path}". The error happened while trying to create the parent directory for the symlink target. Details: ${mkdirError}`;
              throw mkdirError;
            }
            forceSymlinkSync(target, path, opts);
            return { reused: false };
          case "EEXIST":
          case "EISDIR":
            break;
          default:
            throw err;
        }
      }
      let linkString;
      try {
        linkString = (0, fs_1.readlinkSync)(path);
      } catch (err) {
        if ((opts === null || opts === void 0 ? void 0 : opts.overwrite) === false) {
          throw initialErr;
        }
        const parentDir = pathLib.dirname(path);
        let warn;
        if (opts === null || opts === void 0 ? void 0 : opts.renameTried) {
          (0, fs_1.unlinkSync)(path);
          warn = `Symlink wanted name was occupied by directory or file. Old entity removed: "${parentDir}${pathLib.sep}{${pathLib.basename(path)}".`;
        } else {
          const ignore = `.ignored_${pathLib.basename(path)}`;
          try {
            renameOverwrite.sync(path, pathLib.join(parentDir, ignore));
          } catch (error) {
            if (util.types.isNativeError(error) && "code" in error && error.code === "ENOENT") {
              throw initialErr;
            }
            throw error;
          }
          warn = `Symlink wanted name was occupied by directory or file. Old entity moved: "${parentDir}${pathLib.sep}{${pathLib.basename(path)} => ${ignore}".`;
        }
        return {
          ...forceSymlinkSync(target, path, { ...opts, renameTried: true }),
          warn
        };
      }
      if (pathLib.relative(target, linkString) === "") {
        return { reused: true };
      }
      if ((opts === null || opts === void 0 ? void 0 : opts.overwrite) === false) {
        throw initialErr;
      }
      try {
        (0, fs_1.unlinkSync)(path);
      } catch (error) {
        if (!util.types.isNativeError(error) || !("code" in error) || error.code !== "ENOENT") {
          throw error;
        }
      }
      return forceSymlinkSync(target, path, opts);
    }
    module2.exports = symlinkDir;
  }
});

// ../fs/symlink-dependency/lib/symlinkDirectRootDependency.js
var require_symlinkDirectRootDependency = __commonJS({
  "../fs/symlink-dependency/lib/symlinkDirectRootDependency.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.symlinkDirectRootDependency = symlinkDirectRootDependency;
    var fs_1 = require("fs");
    var path_1 = __importDefault(require("path"));
    var util_1 = __importDefault(require("util"));
    var core_loggers_1 = require_lib6();
    var symlink_dir_1 = __importDefault(require_dist3());
    var DEP_TYPE_BY_DEPS_FIELD_NAME = {
      dependencies: "prod",
      devDependencies: "dev",
      optionalDependencies: "optional"
    };
    async function symlinkDirectRootDependency(dependencyLocation, destModulesDir, importAs, opts) {
      let destModulesDirReal;
      try {
        destModulesDirReal = await fs_1.promises.realpath(destModulesDir);
      } catch (err) {
        if (util_1.default.types.isNativeError(err) && "code" in err && err.code === "ENOENT") {
          await fs_1.promises.mkdir(destModulesDir, { recursive: true });
          destModulesDirReal = await fs_1.promises.realpath(destModulesDir);
        } else {
          throw err;
        }
      }
      const dest = path_1.default.join(destModulesDirReal, importAs);
      const { reused } = await (0, symlink_dir_1.default)(dependencyLocation, dest);
      if (reused)
        return;
      core_loggers_1.rootLogger.debug({
        added: {
          dependencyType: opts.fromDependenciesField && DEP_TYPE_BY_DEPS_FIELD_NAME[opts.fromDependenciesField],
          linkedFrom: dependencyLocation,
          name: importAs,
          realName: opts.linkedPackage.name,
          version: opts.linkedPackage.version
        },
        prefix: opts.prefix
      });
    }
  }
});

// ../fs/symlink-dependency/lib/index.js
var require_lib13 = __commonJS({
  "../fs/symlink-dependency/lib/index.js"(exports2) {
    "use strict";
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.symlinkDirectRootDependency = void 0;
    exports2.symlinkDependency = symlinkDependency;
    exports2.symlinkDependencySync = symlinkDependencySync;
    var path_1 = __importDefault(require("path"));
    var core_loggers_1 = require_lib6();
    var symlink_dir_1 = __importDefault(require_dist3());
    var symlinkDirectRootDependency_js_1 = require_symlinkDirectRootDependency();
    Object.defineProperty(exports2, "symlinkDirectRootDependency", { enumerable: true, get: function() {
      return symlinkDirectRootDependency_js_1.symlinkDirectRootDependency;
    } });
    async function symlinkDependency(dependencyRealLocation, destModulesDir, importAs) {
      const link = path_1.default.join(destModulesDir, importAs);
      core_loggers_1.linkLogger.debug({ target: dependencyRealLocation, link });
      return (0, symlink_dir_1.default)(dependencyRealLocation, link);
    }
    function symlinkDependencySync(dependencyRealLocation, destModulesDir, importAs) {
      const link = path_1.default.join(destModulesDir, importAs);
      core_loggers_1.linkLogger.debug({ target: dependencyRealLocation, link });
      return symlink_dir_1.default.sync(dependencyRealLocation, link);
    }
  }
});

// ../node_modules/.pnpm/is-arrayish@0.2.1/node_modules/is-arrayish/index.js
var require_is_arrayish = __commonJS({
  "../node_modules/.pnpm/is-arrayish@0.2.1/node_modules/is-arrayish/index.js"(exports2, module2) {
    "use strict";
    module2.exports = function isArrayish(obj) {
      if (!obj) {
        return false;
      }
      return obj instanceof Array || Array.isArray(obj) || obj.length >= 0 && obj.splice instanceof Function;
    };
  }
});

// ../node_modules/.pnpm/error-ex@1.3.2/node_modules/error-ex/index.js
var require_error_ex = __commonJS({
  "../node_modules/.pnpm/error-ex@1.3.2/node_modules/error-ex/index.js"(exports2, module2) {
    "use strict";
    var util = require("util");
    var isArrayish = require_is_arrayish();
    var errorEx = function errorEx2(name, properties) {
      if (!name || name.constructor !== String) {
        properties = name || {};
        name = Error.name;
      }
      var errorExError = function ErrorEXError(message) {
        if (!this) {
          return new ErrorEXError(message);
        }
        message = message instanceof Error ? message.message : message || this.message;
        Error.call(this, message);
        Error.captureStackTrace(this, errorExError);
        this.name = name;
        Object.defineProperty(this, "message", {
          configurable: true,
          enumerable: false,
          get: function() {
            var newMessage = message.split(/\r?\n/g);
            for (var key in properties) {
              if (!properties.hasOwnProperty(key)) {
                continue;
              }
              var modifier = properties[key];
              if ("message" in modifier) {
                newMessage = modifier.message(this[key], newMessage) || newMessage;
                if (!isArrayish(newMessage)) {
                  newMessage = [newMessage];
                }
              }
            }
            return newMessage.join("\n");
          },
          set: function(v) {
            message = v;
          }
        });
        var overwrittenStack = null;
        var stackDescriptor = Object.getOwnPropertyDescriptor(this, "stack");
        var stackGetter = stackDescriptor.get;
        var stackValue = stackDescriptor.value;
        delete stackDescriptor.value;
        delete stackDescriptor.writable;
        stackDescriptor.set = function(newstack) {
          overwrittenStack = newstack;
        };
        stackDescriptor.get = function() {
          var stack = (overwrittenStack || (stackGetter ? stackGetter.call(this) : stackValue)).split(/\r?\n+/g);
          if (!overwrittenStack) {
            stack[0] = this.name + ": " + this.message;
          }
          var lineCount = 1;
          for (var key in properties) {
            if (!properties.hasOwnProperty(key)) {
              continue;
            }
            var modifier = properties[key];
            if ("line" in modifier) {
              var line = modifier.line(this[key]);
              if (line) {
                stack.splice(lineCount++, 0, "    " + line);
              }
            }
            if ("stack" in modifier) {
              modifier.stack(this[key], stack);
            }
          }
          return stack.join("\n");
        };
        Object.defineProperty(this, "stack", stackDescriptor);
      };
      if (Object.setPrototypeOf) {
        Object.setPrototypeOf(errorExError.prototype, Error.prototype);
        Object.setPrototypeOf(errorExError, Error);
      } else {
        util.inherits(errorExError, Error);
      }
      return errorExError;
    };
    errorEx.append = function(str, def) {
      return {
        message: function(v, message) {
          v = v || def;
          if (v) {
            message[0] += " " + str.replace("%s", v.toString());
          }
          return message;
        }
      };
    };
    errorEx.line = function(str, def) {
      return {
        line: function(v) {
          v = v || def;
          if (v) {
            return str.replace("%s", v.toString());
          }
          return null;
        }
      };
    };
    module2.exports = errorEx;
  }
});

// ../node_modules/.pnpm/json-parse-even-better-errors@2.3.1/node_modules/json-parse-even-better-errors/index.js
var require_json_parse_even_better_errors = __commonJS({
  "../node_modules/.pnpm/json-parse-even-better-errors@2.3.1/node_modules/json-parse-even-better-errors/index.js"(exports2, module2) {
    "use strict";
    var hexify = (char) => {
      const h = char.charCodeAt(0).toString(16).toUpperCase();
      return "0x" + (h.length % 2 ? "0" : "") + h;
    };
    var parseError = (e, txt, context) => {
      if (!txt) {
        return {
          message: e.message + " while parsing empty string",
          position: 0
        };
      }
      const badToken = e.message.match(/^Unexpected token (.) .*position\s+(\d+)/i);
      const errIdx = badToken ? +badToken[2] : e.message.match(/^Unexpected end of JSON.*/i) ? txt.length - 1 : null;
      const msg = badToken ? e.message.replace(/^Unexpected token ./, `Unexpected token ${JSON.stringify(badToken[1])} (${hexify(badToken[1])})`) : e.message;
      if (errIdx !== null && errIdx !== void 0) {
        const start = errIdx <= context ? 0 : errIdx - context;
        const end = errIdx + context >= txt.length ? txt.length : errIdx + context;
        const slice = (start === 0 ? "" : "...") + txt.slice(start, end) + (end === txt.length ? "" : "...");
        const near = txt === slice ? "" : "near ";
        return {
          message: msg + ` while parsing ${near}${JSON.stringify(slice)}`,
          position: errIdx
        };
      } else {
        return {
          message: msg + ` while parsing '${txt.slice(0, context * 2)}'`,
          position: 0
        };
      }
    };
    var JSONParseError = class extends SyntaxError {
      constructor(er, txt, context, caller) {
        context = context || 20;
        const metadata = parseError(er, txt, context);
        super(metadata.message);
        Object.assign(this, metadata);
        this.code = "EJSONPARSE";
        this.systemError = er;
        Error.captureStackTrace(this, caller || this.constructor);
      }
      get name() {
        return this.constructor.name;
      }
      set name(n) {
      }
      get [Symbol.toStringTag]() {
        return this.constructor.name;
      }
    };
    var kIndent = Symbol.for("indent");
    var kNewline = Symbol.for("newline");
    var formatRE = /^\s*[{\[]((?:\r?\n)+)([\s\t]*)/;
    var emptyRE = /^(?:\{\}|\[\])((?:\r?\n)+)?$/;
    var parseJson = (txt, reviver, context) => {
      const parseText = stripBOM(txt);
      context = context || 20;
      try {
        const [, newline = "\n", indent = "  "] = parseText.match(emptyRE) || parseText.match(formatRE) || [, "", ""];
        const result = JSON.parse(parseText, reviver);
        if (result && typeof result === "object") {
          result[kNewline] = newline;
          result[kIndent] = indent;
        }
        return result;
      } catch (e) {
        if (typeof txt !== "string" && !Buffer.isBuffer(txt)) {
          const isEmptyArray = Array.isArray(txt) && txt.length === 0;
          throw Object.assign(new TypeError(
            `Cannot parse ${isEmptyArray ? "an empty array" : String(txt)}`
          ), {
            code: "EJSONPARSE",
            systemError: e
          });
        }
        throw new JSONParseError(e, parseText, context, parseJson);
      }
    };
    var stripBOM = (txt) => String(txt).replace(/^\uFEFF/, "");
    module2.exports = parseJson;
    parseJson.JSONParseError = JSONParseError;
    parseJson.noExceptions = (txt, reviver) => {
      try {
        return JSON.parse(stripBOM(txt), reviver);
      } catch (e) {
      }
    };
  }
});

// ../node_modules/.pnpm/lines-and-columns@1.2.4/node_modules/lines-and-columns/build/index.js
var require_build = __commonJS({
  "../node_modules/.pnpm/lines-and-columns@1.2.4/node_modules/lines-and-columns/build/index.js"(exports2) {
    "use strict";
    exports2.__esModule = true;
    exports2.LinesAndColumns = void 0;
    var LF = "\n";
    var CR = "\r";
    var LinesAndColumns = (
      /** @class */
      (function() {
        function LinesAndColumns2(string) {
          this.string = string;
          var offsets = [0];
          for (var offset = 0; offset < string.length; ) {
            switch (string[offset]) {
              case LF:
                offset += LF.length;
                offsets.push(offset);
                break;
              case CR:
                offset += CR.length;
                if (string[offset] === LF) {
                  offset += LF.length;
                }
                offsets.push(offset);
                break;
              default:
                offset++;
                break;
            }
          }
          this.offsets = offsets;
        }
        LinesAndColumns2.prototype.locationForIndex = function(index) {
          if (index < 0 || index > this.string.length) {
            return null;
          }
          var line = 0;
          var offsets = this.offsets;
          while (offsets[line + 1] <= index) {
            line++;
          }
          var column = index - offsets[line];
          return { line, column };
        };
        LinesAndColumns2.prototype.indexForLocation = function(location) {
          var line = location.line, column = location.column;
          if (line < 0 || line >= this.offsets.length) {
            return null;
          }
          if (column < 0 || column > this.lengthOfLine(line)) {
            return null;
          }
          return this.offsets[line] + column;
        };
        LinesAndColumns2.prototype.lengthOfLine = function(line) {
          var offset = this.offsets[line];
          var nextOffset = line === this.offsets.length - 1 ? this.string.length : this.offsets[line + 1];
          return nextOffset - offset;
        };
        return LinesAndColumns2;
      })()
    );
    exports2.LinesAndColumns = LinesAndColumns;
    exports2["default"] = LinesAndColumns;
  }
});

// ../node_modules/.pnpm/picocolors@1.1.1/node_modules/picocolors/picocolors.js
var require_picocolors = __commonJS({
  "../node_modules/.pnpm/picocolors@1.1.1/node_modules/picocolors/picocolors.js"(exports2, module2) {
    var p = process || {};
    var argv = p.argv || [];
    var env = p.env || {};
    var isColorSupported = !(!!env.NO_COLOR || argv.includes("--no-color")) && (!!env.FORCE_COLOR || argv.includes("--color") || p.platform === "win32" || (p.stdout || {}).isTTY && env.TERM !== "dumb" || !!env.CI);
    var formatter = (open, close, replace = open) => (input) => {
      let string = "" + input, index = string.indexOf(close, open.length);
      return ~index ? open + replaceClose(string, close, replace, index) + close : open + string + close;
    };
    var replaceClose = (string, close, replace, index) => {
      let result = "", cursor = 0;
      do {
        result += string.substring(cursor, index) + replace;
        cursor = index + close.length;
        index = string.indexOf(close, cursor);
      } while (~index);
      return result + string.substring(cursor);
    };
    var createColors = (enabled = isColorSupported) => {
      let f = enabled ? formatter : () => String;
      return {
        isColorSupported: enabled,
        reset: f("\x1B[0m", "\x1B[0m"),
        bold: f("\x1B[1m", "\x1B[22m", "\x1B[22m\x1B[1m"),
        dim: f("\x1B[2m", "\x1B[22m", "\x1B[22m\x1B[2m"),
        italic: f("\x1B[3m", "\x1B[23m"),
        underline: f("\x1B[4m", "\x1B[24m"),
        inverse: f("\x1B[7m", "\x1B[27m"),
        hidden: f("\x1B[8m", "\x1B[28m"),
        strikethrough: f("\x1B[9m", "\x1B[29m"),
        black: f("\x1B[30m", "\x1B[39m"),
        red: f("\x1B[31m", "\x1B[39m"),
        green: f("\x1B[32m", "\x1B[39m"),
        yellow: f("\x1B[33m", "\x1B[39m"),
        blue: f("\x1B[34m", "\x1B[39m"),
        magenta: f("\x1B[35m", "\x1B[39m"),
        cyan: f("\x1B[36m", "\x1B[39m"),
        white: f("\x1B[37m", "\x1B[39m"),
        gray: f("\x1B[90m", "\x1B[39m"),
        bgBlack: f("\x1B[40m", "\x1B[49m"),
        bgRed: f("\x1B[41m", "\x1B[49m"),
        bgGreen: f("\x1B[42m", "\x1B[49m"),
        bgYellow: f("\x1B[43m", "\x1B[49m"),
        bgBlue: f("\x1B[44m", "\x1B[49m"),
        bgMagenta: f("\x1B[45m", "\x1B[49m"),
        bgCyan: f("\x1B[46m", "\x1B[49m"),
        bgWhite: f("\x1B[47m", "\x1B[49m"),
        blackBright: f("\x1B[90m", "\x1B[39m"),
        redBright: f("\x1B[91m", "\x1B[39m"),
        greenBright: f("\x1B[92m", "\x1B[39m"),
        yellowBright: f("\x1B[93m", "\x1B[39m"),
        blueBright: f("\x1B[94m", "\x1B[39m"),
        magentaBright: f("\x1B[95m", "\x1B[39m"),
        cyanBright: f("\x1B[96m", "\x1B[39m"),
        whiteBright: f("\x1B[97m", "\x1B[39m"),
        bgBlackBright: f("\x1B[100m", "\x1B[49m"),
        bgRedBright: f("\x1B[101m", "\x1B[49m"),
        bgGreenBright: f("\x1B[102m", "\x1B[49m"),
        bgYellowBright: f("\x1B[103m", "\x1B[49m"),
        bgBlueBright: f("\x1B[104m", "\x1B[49m"),
        bgMagentaBright: f("\x1B[105m", "\x1B[49m"),
        bgCyanBright: f("\x1B[106m", "\x1B[49m"),
        bgWhiteBright: f("\x1B[107m", "\x1B[49m")
      };
    };
    module2.exports = createColors();
    module2.exports.createColors = createColors;
  }
});

// ../node_modules/.pnpm/js-tokens@4.0.0/node_modules/js-tokens/index.js
var require_js_tokens = __commonJS({
  "../node_modules/.pnpm/js-tokens@4.0.0/node_modules/js-tokens/index.js"(exports2) {
    Object.defineProperty(exports2, "__esModule", {
      value: true
    });
    exports2.default = /((['"])(?:(?!\2|\\).|\\(?:\r\n|[\s\S]))*(\2)?|`(?:[^`\\$]|\\[\s\S]|\$(?!\{)|\$\{(?:[^{}]|\{[^}]*\}?)*\}?)*(`)?)|(\/\/.*)|(\/\*(?:[^*]|\*(?!\/))*(\*\/)?)|(\/(?!\*)(?:\[(?:(?![\]\\]).|\\.)*\]|(?![\/\]\\]).|\\.)+\/(?:(?!\s*(?:\b|[\u0080-\uFFFF$\\'"~({]|[+\-!](?!=)|\.?\d))|[gmiyus]{1,6}\b(?![\u0080-\uFFFF$\\]|\s*(?:[+\-*%&|^<>!=?({]|\/(?![\/*])))))|(0[xX][\da-fA-F]+|0[oO][0-7]+|0[bB][01]+|(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?)|((?!\d)(?:(?!\s)[$\w\u0080-\uFFFF]|\\u[\da-fA-F]{4}|\\u\{[\da-fA-F]+\})+)|(--|\+\+|&&|\|\||=>|\.{3}|(?:[+\-\/%&|^]|\*{1,2}|<{1,2}|>{1,3}|!=?|={1,2})=?|[?~.,:;[\](){}])|(\s+)|(^$|[\s\S])/g;
    exports2.matchToToken = function(match) {
      var token = { type: "invalid", value: match[0], closed: void 0 };
      if (match[1]) token.type = "string", token.closed = !!(match[3] || match[4]);
      else if (match[5]) token.type = "comment";
      else if (match[6]) token.type = "comment", token.closed = !!match[7];
      else if (match[8]) token.type = "regex";
      else if (match[9]) token.type = "number";
      else if (match[10]) token.type = "name";
      else if (match[11]) token.type = "punctuator";
      else if (match[12]) token.type = "whitespace";
      return token;
    };
  }
});

// ../node_modules/.pnpm/@babel+helper-validator-identifier@7.27.1/node_modules/@babel/helper-validator-identifier/lib/identifier.js
var require_identifier = __commonJS({
  "../node_modules/.pnpm/@babel+helper-validator-identifier@7.27.1/node_modules/@babel/helper-validator-identifier/lib/identifier.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", {
      value: true
    });
    exports2.isIdentifierChar = isIdentifierChar;
    exports2.isIdentifierName = isIdentifierName;
    exports2.isIdentifierStart = isIdentifierStart;
    var nonASCIIidentifierStartChars = "\xAA\xB5\xBA\xC0-\xD6\xD8-\xF6\xF8-\u02C1\u02C6-\u02D1\u02E0-\u02E4\u02EC\u02EE\u0370-\u0374\u0376\u0377\u037A-\u037D\u037F\u0386\u0388-\u038A\u038C\u038E-\u03A1\u03A3-\u03F5\u03F7-\u0481\u048A-\u052F\u0531-\u0556\u0559\u0560-\u0588\u05D0-\u05EA\u05EF-\u05F2\u0620-\u064A\u066E\u066F\u0671-\u06D3\u06D5\u06E5\u06E6\u06EE\u06EF\u06FA-\u06FC\u06FF\u0710\u0712-\u072F\u074D-\u07A5\u07B1\u07CA-\u07EA\u07F4\u07F5\u07FA\u0800-\u0815\u081A\u0824\u0828\u0840-\u0858\u0860-\u086A\u0870-\u0887\u0889-\u088E\u08A0-\u08C9\u0904-\u0939\u093D\u0950\u0958-\u0961\u0971-\u0980\u0985-\u098C\u098F\u0990\u0993-\u09A8\u09AA-\u09B0\u09B2\u09B6-\u09B9\u09BD\u09CE\u09DC\u09DD\u09DF-\u09E1\u09F0\u09F1\u09FC\u0A05-\u0A0A\u0A0F\u0A10\u0A13-\u0A28\u0A2A-\u0A30\u0A32\u0A33\u0A35\u0A36\u0A38\u0A39\u0A59-\u0A5C\u0A5E\u0A72-\u0A74\u0A85-\u0A8D\u0A8F-\u0A91\u0A93-\u0AA8\u0AAA-\u0AB0\u0AB2\u0AB3\u0AB5-\u0AB9\u0ABD\u0AD0\u0AE0\u0AE1\u0AF9\u0B05-\u0B0C\u0B0F\u0B10\u0B13-\u0B28\u0B2A-\u0B30\u0B32\u0B33\u0B35-\u0B39\u0B3D\u0B5C\u0B5D\u0B5F-\u0B61\u0B71\u0B83\u0B85-\u0B8A\u0B8E-\u0B90\u0B92-\u0B95\u0B99\u0B9A\u0B9C\u0B9E\u0B9F\u0BA3\u0BA4\u0BA8-\u0BAA\u0BAE-\u0BB9\u0BD0\u0C05-\u0C0C\u0C0E-\u0C10\u0C12-\u0C28\u0C2A-\u0C39\u0C3D\u0C58-\u0C5A\u0C5D\u0C60\u0C61\u0C80\u0C85-\u0C8C\u0C8E-\u0C90\u0C92-\u0CA8\u0CAA-\u0CB3\u0CB5-\u0CB9\u0CBD\u0CDD\u0CDE\u0CE0\u0CE1\u0CF1\u0CF2\u0D04-\u0D0C\u0D0E-\u0D10\u0D12-\u0D3A\u0D3D\u0D4E\u0D54-\u0D56\u0D5F-\u0D61\u0D7A-\u0D7F\u0D85-\u0D96\u0D9A-\u0DB1\u0DB3-\u0DBB\u0DBD\u0DC0-\u0DC6\u0E01-\u0E30\u0E32\u0E33\u0E40-\u0E46\u0E81\u0E82\u0E84\u0E86-\u0E8A\u0E8C-\u0EA3\u0EA5\u0EA7-\u0EB0\u0EB2\u0EB3\u0EBD\u0EC0-\u0EC4\u0EC6\u0EDC-\u0EDF\u0F00\u0F40-\u0F47\u0F49-\u0F6C\u0F88-\u0F8C\u1000-\u102A\u103F\u1050-\u1055\u105A-\u105D\u1061\u1065\u1066\u106E-\u1070\u1075-\u1081\u108E\u10A0-\u10C5\u10C7\u10CD\u10D0-\u10FA\u10FC-\u1248\u124A-\u124D\u1250-\u1256\u1258\u125A-\u125D\u1260-\u1288\u128A-\u128D\u1290-\u12B0\u12B2-\u12B5\u12B8-\u12BE\u12C0\u12C2-\u12C5\u12C8-\u12D6\u12D8-\u1310\u1312-\u1315\u1318-\u135A\u1380-\u138F\u13A0-\u13F5\u13F8-\u13FD\u1401-\u166C\u166F-\u167F\u1681-\u169A\u16A0-\u16EA\u16EE-\u16F8\u1700-\u1711\u171F-\u1731\u1740-\u1751\u1760-\u176C\u176E-\u1770\u1780-\u17B3\u17D7\u17DC\u1820-\u1878\u1880-\u18A8\u18AA\u18B0-\u18F5\u1900-\u191E\u1950-\u196D\u1970-\u1974\u1980-\u19AB\u19B0-\u19C9\u1A00-\u1A16\u1A20-\u1A54\u1AA7\u1B05-\u1B33\u1B45-\u1B4C\u1B83-\u1BA0\u1BAE\u1BAF\u1BBA-\u1BE5\u1C00-\u1C23\u1C4D-\u1C4F\u1C5A-\u1C7D\u1C80-\u1C8A\u1C90-\u1CBA\u1CBD-\u1CBF\u1CE9-\u1CEC\u1CEE-\u1CF3\u1CF5\u1CF6\u1CFA\u1D00-\u1DBF\u1E00-\u1F15\u1F18-\u1F1D\u1F20-\u1F45\u1F48-\u1F4D\u1F50-\u1F57\u1F59\u1F5B\u1F5D\u1F5F-\u1F7D\u1F80-\u1FB4\u1FB6-\u1FBC\u1FBE\u1FC2-\u1FC4\u1FC6-\u1FCC\u1FD0-\u1FD3\u1FD6-\u1FDB\u1FE0-\u1FEC\u1FF2-\u1FF4\u1FF6-\u1FFC\u2071\u207F\u2090-\u209C\u2102\u2107\u210A-\u2113\u2115\u2118-\u211D\u2124\u2126\u2128\u212A-\u2139\u213C-\u213F\u2145-\u2149\u214E\u2160-\u2188\u2C00-\u2CE4\u2CEB-\u2CEE\u2CF2\u2CF3\u2D00-\u2D25\u2D27\u2D2D\u2D30-\u2D67\u2D6F\u2D80-\u2D96\u2DA0-\u2DA6\u2DA8-\u2DAE\u2DB0-\u2DB6\u2DB8-\u2DBE\u2DC0-\u2DC6\u2DC8-\u2DCE\u2DD0-\u2DD6\u2DD8-\u2DDE\u3005-\u3007\u3021-\u3029\u3031-\u3035\u3038-\u303C\u3041-\u3096\u309B-\u309F\u30A1-\u30FA\u30FC-\u30FF\u3105-\u312F\u3131-\u318E\u31A0-\u31BF\u31F0-\u31FF\u3400-\u4DBF\u4E00-\uA48C\uA4D0-\uA4FD\uA500-\uA60C\uA610-\uA61F\uA62A\uA62B\uA640-\uA66E\uA67F-\uA69D\uA6A0-\uA6EF\uA717-\uA71F\uA722-\uA788\uA78B-\uA7CD\uA7D0\uA7D1\uA7D3\uA7D5-\uA7DC\uA7F2-\uA801\uA803-\uA805\uA807-\uA80A\uA80C-\uA822\uA840-\uA873\uA882-\uA8B3\uA8F2-\uA8F7\uA8FB\uA8FD\uA8FE\uA90A-\uA925\uA930-\uA946\uA960-\uA97C\uA984-\uA9B2\uA9CF\uA9E0-\uA9E4\uA9E6-\uA9EF\uA9FA-\uA9FE\uAA00-\uAA28\uAA40-\uAA42\uAA44-\uAA4B\uAA60-\uAA76\uAA7A\uAA7E-\uAAAF\uAAB1\uAAB5\uAAB6\uAAB9-\uAABD\uAAC0\uAAC2\uAADB-\uAADD\uAAE0-\uAAEA\uAAF2-\uAAF4\uAB01-\uAB06\uAB09-\uAB0E\uAB11-\uAB16\uAB20-\uAB26\uAB28-\uAB2E\uAB30-\uAB5A\uAB5C-\uAB69\uAB70-\uABE2\uAC00-\uD7A3\uD7B0-\uD7C6\uD7CB-\uD7FB\uF900-\uFA6D\uFA70-\uFAD9\uFB00-\uFB06\uFB13-\uFB17\uFB1D\uFB1F-\uFB28\uFB2A-\uFB36\uFB38-\uFB3C\uFB3E\uFB40\uFB41\uFB43\uFB44\uFB46-\uFBB1\uFBD3-\uFD3D\uFD50-\uFD8F\uFD92-\uFDC7\uFDF0-\uFDFB\uFE70-\uFE74\uFE76-\uFEFC\uFF21-\uFF3A\uFF41-\uFF5A\uFF66-\uFFBE\uFFC2-\uFFC7\uFFCA-\uFFCF\uFFD2-\uFFD7\uFFDA-\uFFDC";
    var nonASCIIidentifierChars = "\xB7\u0300-\u036F\u0387\u0483-\u0487\u0591-\u05BD\u05BF\u05C1\u05C2\u05C4\u05C5\u05C7\u0610-\u061A\u064B-\u0669\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED\u06F0-\u06F9\u0711\u0730-\u074A\u07A6-\u07B0\u07C0-\u07C9\u07EB-\u07F3\u07FD\u0816-\u0819\u081B-\u0823\u0825-\u0827\u0829-\u082D\u0859-\u085B\u0897-\u089F\u08CA-\u08E1\u08E3-\u0903\u093A-\u093C\u093E-\u094F\u0951-\u0957\u0962\u0963\u0966-\u096F\u0981-\u0983\u09BC\u09BE-\u09C4\u09C7\u09C8\u09CB-\u09CD\u09D7\u09E2\u09E3\u09E6-\u09EF\u09FE\u0A01-\u0A03\u0A3C\u0A3E-\u0A42\u0A47\u0A48\u0A4B-\u0A4D\u0A51\u0A66-\u0A71\u0A75\u0A81-\u0A83\u0ABC\u0ABE-\u0AC5\u0AC7-\u0AC9\u0ACB-\u0ACD\u0AE2\u0AE3\u0AE6-\u0AEF\u0AFA-\u0AFF\u0B01-\u0B03\u0B3C\u0B3E-\u0B44\u0B47\u0B48\u0B4B-\u0B4D\u0B55-\u0B57\u0B62\u0B63\u0B66-\u0B6F\u0B82\u0BBE-\u0BC2\u0BC6-\u0BC8\u0BCA-\u0BCD\u0BD7\u0BE6-\u0BEF\u0C00-\u0C04\u0C3C\u0C3E-\u0C44\u0C46-\u0C48\u0C4A-\u0C4D\u0C55\u0C56\u0C62\u0C63\u0C66-\u0C6F\u0C81-\u0C83\u0CBC\u0CBE-\u0CC4\u0CC6-\u0CC8\u0CCA-\u0CCD\u0CD5\u0CD6\u0CE2\u0CE3\u0CE6-\u0CEF\u0CF3\u0D00-\u0D03\u0D3B\u0D3C\u0D3E-\u0D44\u0D46-\u0D48\u0D4A-\u0D4D\u0D57\u0D62\u0D63\u0D66-\u0D6F\u0D81-\u0D83\u0DCA\u0DCF-\u0DD4\u0DD6\u0DD8-\u0DDF\u0DE6-\u0DEF\u0DF2\u0DF3\u0E31\u0E34-\u0E3A\u0E47-\u0E4E\u0E50-\u0E59\u0EB1\u0EB4-\u0EBC\u0EC8-\u0ECE\u0ED0-\u0ED9\u0F18\u0F19\u0F20-\u0F29\u0F35\u0F37\u0F39\u0F3E\u0F3F\u0F71-\u0F84\u0F86\u0F87\u0F8D-\u0F97\u0F99-\u0FBC\u0FC6\u102B-\u103E\u1040-\u1049\u1056-\u1059\u105E-\u1060\u1062-\u1064\u1067-\u106D\u1071-\u1074\u1082-\u108D\u108F-\u109D\u135D-\u135F\u1369-\u1371\u1712-\u1715\u1732-\u1734\u1752\u1753\u1772\u1773\u17B4-\u17D3\u17DD\u17E0-\u17E9\u180B-\u180D\u180F-\u1819\u18A9\u1920-\u192B\u1930-\u193B\u1946-\u194F\u19D0-\u19DA\u1A17-\u1A1B\u1A55-\u1A5E\u1A60-\u1A7C\u1A7F-\u1A89\u1A90-\u1A99\u1AB0-\u1ABD\u1ABF-\u1ACE\u1B00-\u1B04\u1B34-\u1B44\u1B50-\u1B59\u1B6B-\u1B73\u1B80-\u1B82\u1BA1-\u1BAD\u1BB0-\u1BB9\u1BE6-\u1BF3\u1C24-\u1C37\u1C40-\u1C49\u1C50-\u1C59\u1CD0-\u1CD2\u1CD4-\u1CE8\u1CED\u1CF4\u1CF7-\u1CF9\u1DC0-\u1DFF\u200C\u200D\u203F\u2040\u2054\u20D0-\u20DC\u20E1\u20E5-\u20F0\u2CEF-\u2CF1\u2D7F\u2DE0-\u2DFF\u302A-\u302F\u3099\u309A\u30FB\uA620-\uA629\uA66F\uA674-\uA67D\uA69E\uA69F\uA6F0\uA6F1\uA802\uA806\uA80B\uA823-\uA827\uA82C\uA880\uA881\uA8B4-\uA8C5\uA8D0-\uA8D9\uA8E0-\uA8F1\uA8FF-\uA909\uA926-\uA92D\uA947-\uA953\uA980-\uA983\uA9B3-\uA9C0\uA9D0-\uA9D9\uA9E5\uA9F0-\uA9F9\uAA29-\uAA36\uAA43\uAA4C\uAA4D\uAA50-\uAA59\uAA7B-\uAA7D\uAAB0\uAAB2-\uAAB4\uAAB7\uAAB8\uAABE\uAABF\uAAC1\uAAEB-\uAAEF\uAAF5\uAAF6\uABE3-\uABEA\uABEC\uABED\uABF0-\uABF9\uFB1E\uFE00-\uFE0F\uFE20-\uFE2F\uFE33\uFE34\uFE4D-\uFE4F\uFF10-\uFF19\uFF3F\uFF65";
    var nonASCIIidentifierStart = new RegExp("[" + nonASCIIidentifierStartChars + "]");
    var nonASCIIidentifier = new RegExp("[" + nonASCIIidentifierStartChars + nonASCIIidentifierChars + "]");
    nonASCIIidentifierStartChars = nonASCIIidentifierChars = null;
    var astralIdentifierStartCodes = [0, 11, 2, 25, 2, 18, 2, 1, 2, 14, 3, 13, 35, 122, 70, 52, 268, 28, 4, 48, 48, 31, 14, 29, 6, 37, 11, 29, 3, 35, 5, 7, 2, 4, 43, 157, 19, 35, 5, 35, 5, 39, 9, 51, 13, 10, 2, 14, 2, 6, 2, 1, 2, 10, 2, 14, 2, 6, 2, 1, 4, 51, 13, 310, 10, 21, 11, 7, 25, 5, 2, 41, 2, 8, 70, 5, 3, 0, 2, 43, 2, 1, 4, 0, 3, 22, 11, 22, 10, 30, 66, 18, 2, 1, 11, 21, 11, 25, 71, 55, 7, 1, 65, 0, 16, 3, 2, 2, 2, 28, 43, 28, 4, 28, 36, 7, 2, 27, 28, 53, 11, 21, 11, 18, 14, 17, 111, 72, 56, 50, 14, 50, 14, 35, 39, 27, 10, 22, 251, 41, 7, 1, 17, 2, 60, 28, 11, 0, 9, 21, 43, 17, 47, 20, 28, 22, 13, 52, 58, 1, 3, 0, 14, 44, 33, 24, 27, 35, 30, 0, 3, 0, 9, 34, 4, 0, 13, 47, 15, 3, 22, 0, 2, 0, 36, 17, 2, 24, 20, 1, 64, 6, 2, 0, 2, 3, 2, 14, 2, 9, 8, 46, 39, 7, 3, 1, 3, 21, 2, 6, 2, 1, 2, 4, 4, 0, 19, 0, 13, 4, 31, 9, 2, 0, 3, 0, 2, 37, 2, 0, 26, 0, 2, 0, 45, 52, 19, 3, 21, 2, 31, 47, 21, 1, 2, 0, 185, 46, 42, 3, 37, 47, 21, 0, 60, 42, 14, 0, 72, 26, 38, 6, 186, 43, 117, 63, 32, 7, 3, 0, 3, 7, 2, 1, 2, 23, 16, 0, 2, 0, 95, 7, 3, 38, 17, 0, 2, 0, 29, 0, 11, 39, 8, 0, 22, 0, 12, 45, 20, 0, 19, 72, 200, 32, 32, 8, 2, 36, 18, 0, 50, 29, 113, 6, 2, 1, 2, 37, 22, 0, 26, 5, 2, 1, 2, 31, 15, 0, 328, 18, 16, 0, 2, 12, 2, 33, 125, 0, 80, 921, 103, 110, 18, 195, 2637, 96, 16, 1071, 18, 5, 26, 3994, 6, 582, 6842, 29, 1763, 568, 8, 30, 18, 78, 18, 29, 19, 47, 17, 3, 32, 20, 6, 18, 433, 44, 212, 63, 129, 74, 6, 0, 67, 12, 65, 1, 2, 0, 29, 6135, 9, 1237, 42, 9, 8936, 3, 2, 6, 2, 1, 2, 290, 16, 0, 30, 2, 3, 0, 15, 3, 9, 395, 2309, 106, 6, 12, 4, 8, 8, 9, 5991, 84, 2, 70, 2, 1, 3, 0, 3, 1, 3, 3, 2, 11, 2, 0, 2, 6, 2, 64, 2, 3, 3, 7, 2, 6, 2, 27, 2, 3, 2, 4, 2, 0, 4, 6, 2, 339, 3, 24, 2, 24, 2, 30, 2, 24, 2, 30, 2, 24, 2, 30, 2, 24, 2, 30, 2, 24, 2, 7, 1845, 30, 7, 5, 262, 61, 147, 44, 11, 6, 17, 0, 322, 29, 19, 43, 485, 27, 229, 29, 3, 0, 496, 6, 2, 3, 2, 1, 2, 14, 2, 196, 60, 67, 8, 0, 1205, 3, 2, 26, 2, 1, 2, 0, 3, 0, 2, 9, 2, 3, 2, 0, 2, 0, 7, 0, 5, 0, 2, 0, 2, 0, 2, 2, 2, 1, 2, 0, 3, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 1, 2, 0, 3, 3, 2, 6, 2, 3, 2, 3, 2, 0, 2, 9, 2, 16, 6, 2, 2, 4, 2, 16, 4421, 42719, 33, 4153, 7, 221, 3, 5761, 15, 7472, 16, 621, 2467, 541, 1507, 4938, 6, 4191];
    var astralIdentifierCodes = [509, 0, 227, 0, 150, 4, 294, 9, 1368, 2, 2, 1, 6, 3, 41, 2, 5, 0, 166, 1, 574, 3, 9, 9, 7, 9, 32, 4, 318, 1, 80, 3, 71, 10, 50, 3, 123, 2, 54, 14, 32, 10, 3, 1, 11, 3, 46, 10, 8, 0, 46, 9, 7, 2, 37, 13, 2, 9, 6, 1, 45, 0, 13, 2, 49, 13, 9, 3, 2, 11, 83, 11, 7, 0, 3, 0, 158, 11, 6, 9, 7, 3, 56, 1, 2, 6, 3, 1, 3, 2, 10, 0, 11, 1, 3, 6, 4, 4, 68, 8, 2, 0, 3, 0, 2, 3, 2, 4, 2, 0, 15, 1, 83, 17, 10, 9, 5, 0, 82, 19, 13, 9, 214, 6, 3, 8, 28, 1, 83, 16, 16, 9, 82, 12, 9, 9, 7, 19, 58, 14, 5, 9, 243, 14, 166, 9, 71, 5, 2, 1, 3, 3, 2, 0, 2, 1, 13, 9, 120, 6, 3, 6, 4, 0, 29, 9, 41, 6, 2, 3, 9, 0, 10, 10, 47, 15, 343, 9, 54, 7, 2, 7, 17, 9, 57, 21, 2, 13, 123, 5, 4, 0, 2, 1, 2, 6, 2, 0, 9, 9, 49, 4, 2, 1, 2, 4, 9, 9, 330, 3, 10, 1, 2, 0, 49, 6, 4, 4, 14, 10, 5350, 0, 7, 14, 11465, 27, 2343, 9, 87, 9, 39, 4, 60, 6, 26, 9, 535, 9, 470, 0, 2, 54, 8, 3, 82, 0, 12, 1, 19628, 1, 4178, 9, 519, 45, 3, 22, 543, 4, 4, 5, 9, 7, 3, 6, 31, 3, 149, 2, 1418, 49, 513, 54, 5, 49, 9, 0, 15, 0, 23, 4, 2, 14, 1361, 6, 2, 16, 3, 6, 2, 1, 2, 4, 101, 0, 161, 6, 10, 9, 357, 0, 62, 13, 499, 13, 245, 1, 2, 9, 726, 6, 110, 6, 6, 9, 4759, 9, 787719, 239];
    function isInAstralSet(code, set) {
      let pos = 65536;
      for (let i = 0, length = set.length; i < length; i += 2) {
        pos += set[i];
        if (pos > code) return false;
        pos += set[i + 1];
        if (pos >= code) return true;
      }
      return false;
    }
    function isIdentifierStart(code) {
      if (code < 65) return code === 36;
      if (code <= 90) return true;
      if (code < 97) return code === 95;
      if (code <= 122) return true;
      if (code <= 65535) {
        return code >= 170 && nonASCIIidentifierStart.test(String.fromCharCode(code));
      }
      return isInAstralSet(code, astralIdentifierStartCodes);
    }
    function isIdentifierChar(code) {
      if (code < 48) return code === 36;
      if (code < 58) return true;
      if (code < 65) return false;
      if (code <= 90) return true;
      if (code < 97) return code === 95;
      if (code <= 122) return true;
      if (code <= 65535) {
        return code >= 170 && nonASCIIidentifier.test(String.fromCharCode(code));
      }
      return isInAstralSet(code, astralIdentifierStartCodes) || isInAstralSet(code, astralIdentifierCodes);
    }
    function isIdentifierName(name) {
      let isFirst = true;
      for (let i = 0; i < name.length; i++) {
        let cp = name.charCodeAt(i);
        if ((cp & 64512) === 55296 && i + 1 < name.length) {
          const trail = name.charCodeAt(++i);
          if ((trail & 64512) === 56320) {
            cp = 65536 + ((cp & 1023) << 10) + (trail & 1023);
          }
        }
        if (isFirst) {
          isFirst = false;
          if (!isIdentifierStart(cp)) {
            return false;
          }
        } else if (!isIdentifierChar(cp)) {
          return false;
        }
      }
      return !isFirst;
    }
  }
});

// ../node_modules/.pnpm/@babel+helper-validator-identifier@7.27.1/node_modules/@babel/helper-validator-identifier/lib/keyword.js
var require_keyword = __commonJS({
  "../node_modules/.pnpm/@babel+helper-validator-identifier@7.27.1/node_modules/@babel/helper-validator-identifier/lib/keyword.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", {
      value: true
    });
    exports2.isKeyword = isKeyword;
    exports2.isReservedWord = isReservedWord;
    exports2.isStrictBindOnlyReservedWord = isStrictBindOnlyReservedWord;
    exports2.isStrictBindReservedWord = isStrictBindReservedWord;
    exports2.isStrictReservedWord = isStrictReservedWord;
    var reservedWords = {
      keyword: ["break", "case", "catch", "continue", "debugger", "default", "do", "else", "finally", "for", "function", "if", "return", "switch", "throw", "try", "var", "const", "while", "with", "new", "this", "super", "class", "extends", "export", "import", "null", "true", "false", "in", "instanceof", "typeof", "void", "delete"],
      strict: ["implements", "interface", "let", "package", "private", "protected", "public", "static", "yield"],
      strictBind: ["eval", "arguments"]
    };
    var keywords = new Set(reservedWords.keyword);
    var reservedWordsStrictSet = new Set(reservedWords.strict);
    var reservedWordsStrictBindSet = new Set(reservedWords.strictBind);
    function isReservedWord(word, inModule) {
      return inModule && word === "await" || word === "enum";
    }
    function isStrictReservedWord(word, inModule) {
      return isReservedWord(word, inModule) || reservedWordsStrictSet.has(word);
    }
    function isStrictBindOnlyReservedWord(word) {
      return reservedWordsStrictBindSet.has(word);
    }
    function isStrictBindReservedWord(word, inModule) {
      return isStrictReservedWord(word, inModule) || isStrictBindOnlyReservedWord(word);
    }
    function isKeyword(word) {
      return keywords.has(word);
    }
  }
});

// ../node_modules/.pnpm/@babel+helper-validator-identifier@7.27.1/node_modules/@babel/helper-validator-identifier/lib/index.js
var require_lib14 = __commonJS({
  "../node_modules/.pnpm/@babel+helper-validator-identifier@7.27.1/node_modules/@babel/helper-validator-identifier/lib/index.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", {
      value: true
    });
    Object.defineProperty(exports2, "isIdentifierChar", {
      enumerable: true,
      get: function() {
        return _identifier.isIdentifierChar;
      }
    });
    Object.defineProperty(exports2, "isIdentifierName", {
      enumerable: true,
      get: function() {
        return _identifier.isIdentifierName;
      }
    });
    Object.defineProperty(exports2, "isIdentifierStart", {
      enumerable: true,
      get: function() {
        return _identifier.isIdentifierStart;
      }
    });
    Object.defineProperty(exports2, "isKeyword", {
      enumerable: true,
      get: function() {
        return _keyword.isKeyword;
      }
    });
    Object.defineProperty(exports2, "isReservedWord", {
      enumerable: true,
      get: function() {
        return _keyword.isReservedWord;
      }
    });
    Object.defineProperty(exports2, "isStrictBindOnlyReservedWord", {
      enumerable: true,
      get: function() {
        return _keyword.isStrictBindOnlyReservedWord;
      }
    });
    Object.defineProperty(exports2, "isStrictBindReservedWord", {
      enumerable: true,
      get: function() {
        return _keyword.isStrictBindReservedWord;
      }
    });
    Object.defineProperty(exports2, "isStrictReservedWord", {
      enumerable: true,
      get: function() {
        return _keyword.isStrictReservedWord;
      }
    });
    var _identifier = require_identifier();
    var _keyword = require_keyword();
  }
});

// ../node_modules/.pnpm/@babel+code-frame@7.27.1/node_modules/@babel/code-frame/lib/index.js
var require_lib15 = __commonJS({
  "../node_modules/.pnpm/@babel+code-frame@7.27.1/node_modules/@babel/code-frame/lib/index.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    var picocolors = require_picocolors();
    var jsTokens = require_js_tokens();
    var helperValidatorIdentifier = require_lib14();
    function isColorSupported() {
      return typeof process === "object" && (process.env.FORCE_COLOR === "0" || process.env.FORCE_COLOR === "false") ? false : picocolors.isColorSupported;
    }
    var compose = (f, g) => (v) => f(g(v));
    function buildDefs(colors) {
      return {
        keyword: colors.cyan,
        capitalized: colors.yellow,
        jsxIdentifier: colors.yellow,
        punctuator: colors.yellow,
        number: colors.magenta,
        string: colors.green,
        regex: colors.magenta,
        comment: colors.gray,
        invalid: compose(compose(colors.white, colors.bgRed), colors.bold),
        gutter: colors.gray,
        marker: compose(colors.red, colors.bold),
        message: compose(colors.red, colors.bold),
        reset: colors.reset
      };
    }
    var defsOn = buildDefs(picocolors.createColors(true));
    var defsOff = buildDefs(picocolors.createColors(false));
    function getDefs(enabled) {
      return enabled ? defsOn : defsOff;
    }
    var sometimesKeywords = /* @__PURE__ */ new Set(["as", "async", "from", "get", "of", "set"]);
    var NEWLINE$1 = /\r\n|[\n\r\u2028\u2029]/;
    var BRACKET = /^[()[\]{}]$/;
    var tokenize;
    {
      const JSX_TAG = /^[a-z][\w-]*$/i;
      const getTokenType = function(token, offset, text) {
        if (token.type === "name") {
          if (helperValidatorIdentifier.isKeyword(token.value) || helperValidatorIdentifier.isStrictReservedWord(token.value, true) || sometimesKeywords.has(token.value)) {
            return "keyword";
          }
          if (JSX_TAG.test(token.value) && (text[offset - 1] === "<" || text.slice(offset - 2, offset) === "</")) {
            return "jsxIdentifier";
          }
          if (token.value[0] !== token.value[0].toLowerCase()) {
            return "capitalized";
          }
        }
        if (token.type === "punctuator" && BRACKET.test(token.value)) {
          return "bracket";
        }
        if (token.type === "invalid" && (token.value === "@" || token.value === "#")) {
          return "punctuator";
        }
        return token.type;
      };
      tokenize = function* (text) {
        let match;
        while (match = jsTokens.default.exec(text)) {
          const token = jsTokens.matchToToken(match);
          yield {
            type: getTokenType(token, match.index, text),
            value: token.value
          };
        }
      };
    }
    function highlight(text) {
      if (text === "") return "";
      const defs = getDefs(true);
      let highlighted = "";
      for (const {
        type,
        value
      } of tokenize(text)) {
        if (type in defs) {
          highlighted += value.split(NEWLINE$1).map((str) => defs[type](str)).join("\n");
        } else {
          highlighted += value;
        }
      }
      return highlighted;
    }
    var deprecationWarningShown = false;
    var NEWLINE = /\r\n|[\n\r\u2028\u2029]/;
    function getMarkerLines(loc, source, opts) {
      const startLoc = Object.assign({
        column: 0,
        line: -1
      }, loc.start);
      const endLoc = Object.assign({}, startLoc, loc.end);
      const {
        linesAbove = 2,
        linesBelow = 3
      } = opts || {};
      const startLine = startLoc.line;
      const startColumn = startLoc.column;
      const endLine = endLoc.line;
      const endColumn = endLoc.column;
      let start = Math.max(startLine - (linesAbove + 1), 0);
      let end = Math.min(source.length, endLine + linesBelow);
      if (startLine === -1) {
        start = 0;
      }
      if (endLine === -1) {
        end = source.length;
      }
      const lineDiff = endLine - startLine;
      const markerLines = {};
      if (lineDiff) {
        for (let i = 0; i <= lineDiff; i++) {
          const lineNumber = i + startLine;
          if (!startColumn) {
            markerLines[lineNumber] = true;
          } else if (i === 0) {
            const sourceLength = source[lineNumber - 1].length;
            markerLines[lineNumber] = [startColumn, sourceLength - startColumn + 1];
          } else if (i === lineDiff) {
            markerLines[lineNumber] = [0, endColumn];
          } else {
            const sourceLength = source[lineNumber - i].length;
            markerLines[lineNumber] = [0, sourceLength];
          }
        }
      } else {
        if (startColumn === endColumn) {
          if (startColumn) {
            markerLines[startLine] = [startColumn, 0];
          } else {
            markerLines[startLine] = true;
          }
        } else {
          markerLines[startLine] = [startColumn, endColumn - startColumn];
        }
      }
      return {
        start,
        end,
        markerLines
      };
    }
    function codeFrameColumns(rawLines, loc, opts = {}) {
      const shouldHighlight = opts.forceColor || isColorSupported() && opts.highlightCode;
      const defs = getDefs(shouldHighlight);
      const lines = rawLines.split(NEWLINE);
      const {
        start,
        end,
        markerLines
      } = getMarkerLines(loc, lines, opts);
      const hasColumns = loc.start && typeof loc.start.column === "number";
      const numberMaxWidth = String(end).length;
      const highlightedLines = shouldHighlight ? highlight(rawLines) : rawLines;
      let frame = highlightedLines.split(NEWLINE, end).slice(start, end).map((line, index2) => {
        const number = start + 1 + index2;
        const paddedNumber = ` ${number}`.slice(-numberMaxWidth);
        const gutter = ` ${paddedNumber} |`;
        const hasMarker = markerLines[number];
        const lastMarkerLine = !markerLines[number + 1];
        if (hasMarker) {
          let markerLine = "";
          if (Array.isArray(hasMarker)) {
            const markerSpacing = line.slice(0, Math.max(hasMarker[0] - 1, 0)).replace(/[^\t]/g, " ");
            const numberOfMarkers = hasMarker[1] || 1;
            markerLine = ["\n ", defs.gutter(gutter.replace(/\d/g, " ")), " ", markerSpacing, defs.marker("^").repeat(numberOfMarkers)].join("");
            if (lastMarkerLine && opts.message) {
              markerLine += " " + defs.message(opts.message);
            }
          }
          return [defs.marker(">"), defs.gutter(gutter), line.length > 0 ? ` ${line}` : "", markerLine].join("");
        } else {
          return ` ${defs.gutter(gutter)}${line.length > 0 ? ` ${line}` : ""}`;
        }
      }).join("\n");
      if (opts.message && !hasColumns) {
        frame = `${" ".repeat(numberMaxWidth + 1)}${opts.message}
${frame}`;
      }
      if (shouldHighlight) {
        return defs.reset(frame);
      } else {
        return frame;
      }
    }
    function index(rawLines, lineNumber, colNumber, opts = {}) {
      if (!deprecationWarningShown) {
        deprecationWarningShown = true;
        const message = "Passing lineNumber and colNumber is deprecated to @babel/code-frame. Please use `codeFrameColumns`.";
        if (process.emitWarning) {
          process.emitWarning(message, "DeprecationWarning");
        } else {
          const deprecationError = new Error(message);
          deprecationError.name = "DeprecationWarning";
          console.warn(new Error(message));
        }
      }
      colNumber = Math.max(colNumber, 0);
      const location = {
        start: {
          column: colNumber,
          line: lineNumber
        }
      };
      return codeFrameColumns(rawLines, location, opts);
    }
    exports2.codeFrameColumns = codeFrameColumns;
    exports2.default = index;
    exports2.highlight = highlight;
  }
});

// ../node_modules/.pnpm/parse-json@5.2.0/node_modules/parse-json/index.js
var require_parse_json = __commonJS({
  "../node_modules/.pnpm/parse-json@5.2.0/node_modules/parse-json/index.js"(exports2, module2) {
    "use strict";
    var errorEx = require_error_ex();
    var fallback = require_json_parse_even_better_errors();
    var { default: LinesAndColumns } = require_build();
    var { codeFrameColumns } = require_lib15();
    var JSONError = errorEx("JSONError", {
      fileName: errorEx.append("in %s"),
      codeFrame: errorEx.append("\n\n%s\n")
    });
    var parseJson = (string, reviver, filename) => {
      if (typeof reviver === "string") {
        filename = reviver;
        reviver = null;
      }
      try {
        try {
          return JSON.parse(string, reviver);
        } catch (error) {
          fallback(string, reviver);
          throw error;
        }
      } catch (error) {
        error.message = error.message.replace(/\n/g, "");
        const indexMatch = error.message.match(/in JSON at position (\d+) while parsing/);
        const jsonError = new JSONError(error);
        if (filename) {
          jsonError.fileName = filename;
        }
        if (indexMatch && indexMatch.length > 0) {
          const lines = new LinesAndColumns(string);
          const index = Number(indexMatch[1]);
          const location = lines.locationForIndex(index);
          const codeFrame = codeFrameColumns(
            string,
            { start: { line: location.line + 1, column: location.column + 1 } },
            { highlightCode: true }
          );
          jsonError.codeFrame = codeFrame;
        }
        throw jsonError;
      }
    };
    parseJson.JSONError = JSONError;
    module2.exports = parseJson;
  }
});

// ../node_modules/.pnpm/load-json-file@6.2.0/node_modules/load-json-file/index.js
var require_load_json_file = __commonJS({
  "../node_modules/.pnpm/load-json-file@6.2.0/node_modules/load-json-file/index.js"(exports2, module2) {
    "use strict";
    var path = require("path");
    var { promisify } = require("util");
    var fs = require_graceful_fs();
    var stripBom = require_strip_bom();
    var parseJson = require_parse_json();
    var parse = (data, filePath, options = {}) => {
      data = stripBom(data);
      if (typeof options.beforeParse === "function") {
        data = options.beforeParse(data);
      }
      return parseJson(data, options.reviver, path.relative(process.cwd(), filePath));
    };
    module2.exports = async (filePath, options) => parse(await promisify(fs.readFile)(filePath, "utf8"), filePath, options);
    module2.exports.sync = (filePath, options) => parse(fs.readFileSync(filePath, "utf8"), filePath, options);
  }
});

// ../worker/lib/start.js
var require_start = __commonJS({
  "../worker/lib/start.js"(exports2) {
    "use strict";
    var __createBinding = exports2 && exports2.__createBinding || (Object.create ? (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      var desc = Object.getOwnPropertyDescriptor(m, k);
      if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
        desc = { enumerable: true, get: function() {
          return m[k];
        } };
      }
      Object.defineProperty(o, k2, desc);
    }) : (function(o, m, k, k2) {
      if (k2 === void 0) k2 = k;
      o[k2] = m[k];
    }));
    var __setModuleDefault = exports2 && exports2.__setModuleDefault || (Object.create ? (function(o, v) {
      Object.defineProperty(o, "default", { enumerable: true, value: v });
    }) : function(o, v) {
      o["default"] = v;
    });
    var __importStar = exports2 && exports2.__importStar || function(mod) {
      if (mod && mod.__esModule) return mod;
      var result = {};
      if (mod != null) {
        for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
      }
      __setModuleDefault(result, mod);
      return result;
    };
    var __importDefault = exports2 && exports2.__importDefault || function(mod) {
      return mod && mod.__esModule ? mod : { "default": mod };
    };
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.startWorker = startWorker;
    var path_1 = __importDefault(require("path"));
    var fs_1 = __importDefault(require("fs"));
    var graceful_fs_1 = __importDefault(require_lib());
    var create_cafs_store_1 = require_lib9();
    var crypto = __importStar(require_lib10());
    var exec_pkg_requires_build_1 = require_lib11();
    var fs_hard_link_dir_1 = require_lib12();
    var store_cafs_1 = require_lib4();
    var symlink_dependency_1 = require_lib13();
    var load_json_file_1 = require_load_json_file();
    var worker_threads_1 = require("worker_threads");
    var INTEGRITY_REGEX = /^([^-]+)-([a-z0-9+/=]+)$/i;
    function startWorker() {
      process.on("uncaughtException", (err) => {
        console.error(err);
      });
      worker_threads_1.parentPort.on("message", handleMessage);
    }
    var cafsCache = /* @__PURE__ */ new Map();
    var cafsStoreCache = /* @__PURE__ */ new Map();
    var cafsLocker = /* @__PURE__ */ new Map();
    async function handleMessage(message) {
      if (message === false) {
        worker_threads_1.parentPort.off("message", handleMessage);
        process.exit(0);
      }
      try {
        switch (message.type) {
          case "extract": {
            worker_threads_1.parentPort.postMessage(addTarballToStore(message));
            break;
          }
          case "link": {
            worker_threads_1.parentPort.postMessage(importPackage(message));
            break;
          }
          case "add-dir": {
            worker_threads_1.parentPort.postMessage(addFilesFromDir(message));
            break;
          }
          case "init-store": {
            worker_threads_1.parentPort.postMessage(initStore(message));
            break;
          }
          case "readPkgFromCafs": {
            let { storeDir, filesIndexFile, readManifest, verifyStoreIntegrity } = message;
            let pkgFilesIndex;
            try {
              pkgFilesIndex = (0, load_json_file_1.sync)(filesIndexFile);
            } catch {
            }
            if (!pkgFilesIndex) {
              worker_threads_1.parentPort.postMessage({
                status: "success",
                value: {
                  verified: false,
                  pkgFilesIndex: null
                }
              });
              return;
            }
            let verifyResult;
            if (pkgFilesIndex.requiresBuild == null) {
              readManifest = true;
            }
            if (verifyStoreIntegrity) {
              verifyResult = (0, store_cafs_1.checkPkgFilesIntegrity)(storeDir, pkgFilesIndex, readManifest);
            } else {
              verifyResult = {
                passed: true,
                manifest: readManifest ? (0, store_cafs_1.readManifestFromStore)(storeDir, pkgFilesIndex) : void 0
              };
            }
            const requiresBuild = pkgFilesIndex.requiresBuild ?? (0, exec_pkg_requires_build_1.pkgRequiresBuild)(verifyResult.manifest, pkgFilesIndex.files);
            worker_threads_1.parentPort.postMessage({
              status: "success",
              value: {
                verified: verifyResult.passed,
                manifest: verifyResult.manifest,
                pkgFilesIndex,
                requiresBuild
              }
            });
            break;
          }
          case "symlinkAllModules": {
            worker_threads_1.parentPort.postMessage(symlinkAllModules(message));
            break;
          }
          case "hardLinkDir": {
            (0, fs_hard_link_dir_1.hardLinkDir)(message.src, message.destDirs);
            worker_threads_1.parentPort.postMessage({ status: "success" });
            break;
          }
        }
      } catch (e) {
        worker_threads_1.parentPort.postMessage({
          status: "error",
          error: {
            code: e.code,
            message: e.message ?? e.toString()
          }
        });
      }
    }
    function addTarballToStore({ buffer, storeDir, integrity, filesIndexFile, appendManifest }) {
      if (integrity) {
        const [, algo, integrityHash] = integrity.match(INTEGRITY_REGEX);
        const normalizedRemoteHash = Buffer.from(integrityHash, "base64").toString("hex");
        const calculatedHash = crypto.hash(algo, buffer, "hex");
        if (calculatedHash !== normalizedRemoteHash) {
          return {
            status: "error",
            error: {
              type: "integrity_validation_failed",
              algorithm: algo,
              expected: integrity,
              found: `${algo}-${Buffer.from(calculatedHash, "hex").toString("base64")}`
            }
          };
        }
      }
      if (!cafsCache.has(storeDir)) {
        cafsCache.set(storeDir, (0, store_cafs_1.createCafs)(storeDir));
      }
      const cafs = cafsCache.get(storeDir);
      let { filesIndex, manifest } = cafs.addFilesFromTarball(buffer, true);
      if (appendManifest && manifest == null) {
        manifest = appendManifest;
        addManifestToCafs(cafs, filesIndex, appendManifest);
      }
      const { filesIntegrity, filesMap } = processFilesIndex(filesIndex);
      const requiresBuild = writeFilesIndexFile(filesIndexFile, { manifest: manifest ?? {}, files: filesIntegrity });
      return {
        status: "success",
        value: {
          filesIndex: filesMap,
          manifest,
          requiresBuild,
          integrity: integrity ?? calcIntegrity(buffer)
        }
      };
    }
    function calcIntegrity(buffer) {
      const calculatedHash = crypto.hash("sha512", buffer, "hex");
      return `sha512-${Buffer.from(calculatedHash, "hex").toString("base64")}`;
    }
    function initStore({ storeDir }) {
      fs_1.default.mkdirSync(storeDir, { recursive: true });
      const hexChars = "0123456789abcdef".split("");
      for (const subDir of ["files", "index"]) {
        const subDirPath = path_1.default.join(storeDir, subDir);
        try {
          fs_1.default.mkdirSync(subDirPath);
        } catch {
        }
        for (const hex1 of hexChars) {
          for (const hex2 of hexChars) {
            try {
              fs_1.default.mkdirSync(path_1.default.join(subDirPath, `${hex1}${hex2}`));
            } catch {
            }
          }
        }
      }
      return { status: "success" };
    }
    function addFilesFromDir({ appendManifest, dir, files, filesIndexFile, sideEffectsCacheKey, storeDir }) {
      if (!cafsCache.has(storeDir)) {
        cafsCache.set(storeDir, (0, store_cafs_1.createCafs)(storeDir));
      }
      const cafs = cafsCache.get(storeDir);
      let { filesIndex, manifest } = cafs.addFilesFromDir(dir, {
        files,
        readManifest: true
      });
      if (appendManifest && manifest == null) {
        manifest = appendManifest;
        addManifestToCafs(cafs, filesIndex, appendManifest);
      }
      const { filesIntegrity, filesMap } = processFilesIndex(filesIndex);
      let requiresBuild;
      if (sideEffectsCacheKey) {
        let filesIndex2;
        try {
          filesIndex2 = (0, load_json_file_1.sync)(filesIndexFile);
        } catch {
          return {
            status: "success",
            value: {
              filesIndex: filesMap,
              manifest,
              requiresBuild: (0, exec_pkg_requires_build_1.pkgRequiresBuild)(manifest, filesIntegrity)
            }
          };
        }
        filesIndex2.sideEffects = filesIndex2.sideEffects ?? {};
        filesIndex2.sideEffects[sideEffectsCacheKey] = calculateDiff(filesIndex2.files, filesIntegrity);
        if (filesIndex2.requiresBuild == null) {
          requiresBuild = (0, exec_pkg_requires_build_1.pkgRequiresBuild)(manifest, filesIntegrity);
        } else {
          requiresBuild = filesIndex2.requiresBuild;
        }
        writeJsonFile(filesIndexFile, filesIndex2);
      } else {
        requiresBuild = writeFilesIndexFile(filesIndexFile, { manifest: manifest ?? {}, files: filesIntegrity });
      }
      return { status: "success", value: { filesIndex: filesMap, manifest, requiresBuild } };
    }
    function addManifestToCafs(cafs, filesIndex, manifest) {
      const fileBuffer = Buffer.from(JSON.stringify(manifest, null, 2), "utf8");
      const mode = 420;
      filesIndex["package.json"] = {
        mode,
        size: fileBuffer.length,
        ...cafs.addFile(fileBuffer, mode)
      };
    }
    function calculateDiff(baseFiles, sideEffectsFiles) {
      const deleted = [];
      const added = {};
      for (const file of /* @__PURE__ */ new Set([...Object.keys(baseFiles), ...Object.keys(sideEffectsFiles)])) {
        if (!sideEffectsFiles[file]) {
          deleted.push(file);
        } else if (!baseFiles[file] || baseFiles[file].integrity !== sideEffectsFiles[file].integrity || baseFiles[file].mode !== sideEffectsFiles[file].mode) {
          added[file] = sideEffectsFiles[file];
        }
      }
      const diff = {};
      if (deleted.length > 0) {
        diff.deleted = deleted;
      }
      if (Object.keys(added).length > 0) {
        diff.added = added;
      }
      return diff;
    }
    function processFilesIndex(filesIndex) {
      const filesIntegrity = {};
      const filesMap = {};
      for (const [k, { checkedAt, filePath, integrity, mode, size }] of Object.entries(filesIndex)) {
        filesIntegrity[k] = {
          checkedAt,
          integrity: integrity.toString(),
          // TODO: use the raw Integrity object
          mode,
          size
        };
        filesMap[k] = filePath;
      }
      return { filesIntegrity, filesMap };
    }
    function importPackage({ storeDir, packageImportMethod, filesResponse, sideEffectsCacheKey, targetDir, requiresBuild, force, keepModulesDir, disableRelinkLocalDirDeps }) {
      const cacheKey = JSON.stringify({ storeDir, packageImportMethod });
      if (!cafsStoreCache.has(cacheKey)) {
        cafsStoreCache.set(cacheKey, (0, create_cafs_store_1.createCafsStore)(storeDir, { packageImportMethod, cafsLocker }));
      }
      const cafsStore = cafsStoreCache.get(cacheKey);
      const { importMethod, isBuilt } = cafsStore.importPackage(targetDir, {
        filesResponse,
        force,
        disableRelinkLocalDirDeps,
        requiresBuild,
        sideEffectsCacheKey,
        keepModulesDir
      });
      return { status: "success", value: { isBuilt, importMethod } };
    }
    function symlinkAllModules(opts) {
      for (const dep of opts.deps) {
        for (const [alias, pkgDir] of Object.entries(dep.children)) {
          if (alias !== dep.name) {
            (0, symlink_dependency_1.symlinkDependencySync)(pkgDir, dep.modules, alias);
          }
        }
      }
      return { status: "success" };
    }
    function writeFilesIndexFile(filesIndexFile, { manifest, files, sideEffects }) {
      const requiresBuild = (0, exec_pkg_requires_build_1.pkgRequiresBuild)(manifest, files);
      const filesIndex = {
        name: manifest.name,
        version: manifest.version,
        requiresBuild,
        files,
        sideEffects
      };
      writeJsonFile(filesIndexFile, filesIndex);
      return requiresBuild;
    }
    function writeJsonFile(filePath, data) {
      const targetDir = path_1.default.dirname(filePath);
      fs_1.default.mkdirSync(targetDir, { recursive: true });
      const temp = `${filePath.slice(0, -11)}${process.pid}`;
      graceful_fs_1.default.writeFileSync(temp, JSON.stringify(data));
      (0, store_cafs_1.optimisticRenameOverwrite)(temp, filePath);
    }
  }
});

// ../worker/lib/worker.js
Object.defineProperty(exports, "__esModule", { value: true });
var start_js_1 = require_start();
(0, start_js_1.startWorker)();
/*! Bundled license information:

is-windows/index.js:
  (*!
   * is-windows <https://github.com/jonschlinkert/is-windows>
   *
   * Copyright © 2015-2018, Jon Schlinkert.
   * Released under the MIT License.
   *)
*/
